"""Daily summary and receivables: totals matching the payments and the ledger, constant queries."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from skeleton.contrib.ledger.service_api import LedgerService

from ..service_api import ChargeItemInput, FinanceService
from .helpers import add_price, new_patient, prepare


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    with clinic.as_user(clinic.a.reception) as actor:
        service().open_session(actor=actor, idempotency_key="open")
    return clinic


def charge_and_pay(ready, key, amounts, due_date=None):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        charge = (
            service()
            .create_charge(
                actor=actor,
                patient_id=patient.sysid,
                items=(ChargeItemInput(code="C1"),),
                due_date=due_date,
                idempotency_key=key,
            )
            .charge
        )
        for index, (method, amount) in enumerate(amounts):
            current = service().charge(actor=actor, charge_id=charge.sysid).charge
            service().register_payment(
                actor=actor,
                charge_id=charge.sysid,
                method=method,
                amount=amount,
                expected_revision=current.revision,
                idempotency_key=f"{key}-{index}",
                issue_receipt=False,
            )
    return charge


def test_daily_summary_matches_the_payments_and_the_ledger(ready):
    charge_and_pay(ready, "a", [("cash", 10000), ("pix", 15000)])
    charge_and_pay(ready, "b", [("cash", 5000)])
    today = timezone.localdate()
    with ready.as_user(ready.a.reception) as actor:
        summary = service().daily_summary(actor=actor, date=today)
    assert {(item.method, item.amount) for item in summary.by_method} == {("cash", 15000), ("pix", 15000)}
    assert (summary.received, summary.charges_created, summary.charged, summary.open_due) == (30000, 2, 50000, 1)
    with ready.as_user(ready.a.admin) as admin:
        (desk,) = service().desks(actor=admin)
        balance = LedgerService().balance(
            actor=admin, as_of=today, account_key="med_finance.cash", book_id=desk.book_id
        )
    assert balance.balance == 15000


def test_receivables_by_days_overdue(ready):
    today = timezone.localdate()
    charge_and_pay(ready, "now", [], due_date=today)
    charge_and_pay(ready, "late", [("cash", 5000)], due_date=today - timedelta(days=45))
    charge_and_pay(ready, "old", [], due_date=today - timedelta(days=120))
    with ready.as_user(ready.a.reception) as actor:
        report = service().receivables(actor=actor)
    amounts = {item.name: (item.amount, item.count) for item in report.buckets}
    assert amounts == {"current": (25000, 1), "1-30": (0, 0), "31-60": (20000, 1), "61-90": (0, 0), "90+": (25000, 1)}
    assert report.total == 70000


def test_query_count_does_not_grow_with_the_charges(ready):
    today = timezone.localdate()

    def count():
        with ready.as_user(ready.a.reception) as actor, CaptureQueriesContext(connection) as context:
            service().daily_summary(actor=actor, date=today)
            service().receivables(actor=actor)
        return len(context)

    charge_and_pay(ready, "one", [("cash", 1000)])
    few = count()
    for key in ("two", "three", "four"):
        charge_and_pay(ready, key, [("pix", 1000)])
    assert count() == few


def test_report_pages(ready):
    charge_and_pay(ready, "a", [("cash", 10000)])
    client = Client()
    client.force_login(ready.a.reception)
    for name in ("daily", "receivables"):
        response = client.get(reverse(f"med_finance:{name}", args=(ready.org_a.pk,)))
        assert response.status_code == 200 and "R$" in response.content.decode()
    doctor = Client()
    doctor.force_login(ready.a.doctor)
    assert doctor.get(reverse("med_finance:daily", args=(ready.org_a.pk,))).status_code == 404
