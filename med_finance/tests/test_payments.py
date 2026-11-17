"""Payments: settlement in the ledger, partial and full payment, reversal, sessions and CAS."""

import pytest

from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api import Conflict, InvalidInput

from ..service_api import ChargeItemInput, FinanceService
from .helpers import add_price, new_patient, prepare


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    return clinic


def charge_of(ready, key="c"):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        return (
            service()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key=key
            )
            .charge
        )


def open_desk(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().open_session(actor=actor, opening_amount=0, idempotency_key="open")


def pay(ready, charge, amount, key, method="cash", **values):
    with ready.as_user(ready.a.reception) as actor:
        current = service().charge(actor=actor, charge_id=charge.sysid).charge
        return service().register_payment(
            actor=actor,
            charge_id=charge.sysid,
            method=method,
            amount=amount,
            expected_revision=values.pop("expected_revision", current.revision),
            idempotency_key=key,
            issue_receipt=False,
            **values,
        )


def test_partial_then_full_payment(ready, monkeypatch):
    charge = charge_of(ready)
    with pytest.raises(Conflict) as error:
        pay(ready, charge, 1000, "early")
    assert error.value.code == "no_open_session"
    session = open_desk(ready)
    published = []
    from skeleton.service_api.events import EventService

    original = EventService.publish
    monkeypatch.setattr(
        EventService, "publish", lambda self, **kw: published.append(kw["event_type"]) or original(self, **kw)
    )
    first = pay(ready, charge, 10000, "p1")
    assert pay(ready, charge, 10000, "p1").sysid == first.sysid
    with ready.as_user(ready.a.reception) as actor:
        assert service().charge(actor=actor, charge_id=charge.sysid).charge.status == "partially_paid"
    with pytest.raises(InvalidInput):
        pay(ready, charge, 20000, "too-much")
    pay(ready, charge, 15000, "p2", method="pix")
    with ready.as_user(ready.a.reception) as actor:
        detail = service().charge(actor=actor, charge_id=charge.sysid).charge
        assert (detail.status, detail.paid_total, detail.balance) == ("paid", 25000, 0)
        (title,) = LedgerService().titles_for_source(
            actor=actor, table_key="med_finance.charge", record_id=charge.sysid
        )
        settlements = LedgerService().settlements(actor=actor, title_id=title.sysid)
        report = service().session_report(actor=actor, session_id=session.sysid)
    assert title.status == "settled" and sorted(item.method for item in settlements) == ["cash", "pix"]
    assert {(item.method, item.amount) for item in report.by_method} == {("cash", 10000), ("pix", 15000)}
    assert report.expected_cash == 10000
    assert published.count("med_finance.charge_paid") == 1 and published.count("med_finance.payment_registered") == 2
    with pytest.raises(Conflict) as error:
        pay(ready, charge, 1, "after")
    assert error.value.code == "not_open"


def test_stale_revision_and_validation(ready, subtests):
    charge = charge_of(ready)
    open_desk(ready)
    pay(ready, charge, 1000, "p1")
    with pytest.raises(Conflict) as error:
        pay(ready, charge, 1000, "p2", expected_revision=charge.revision)
    assert error.value.code == "stale_revision"
    cases = {
        "method": {"method": "barter"},
        "installments on debit": {"method": "debit_card", "installments": 3},
        "installments": {"method": "credit_card", "installments": 30},
    }
    for name, values in cases.items():
        with subtests.test(name), pytest.raises(InvalidInput):
            pay(ready, charge, 1000, f"bad-{name}", **values)
    assert pay(ready, charge, 1000, "card", method="credit_card", installments=3).installments == 3


def test_reverse_reopens_the_charge_and_the_title(ready):
    charge = charge_of(ready)
    open_desk(ready)
    payment = pay(ready, charge, 25000, "p1")
    with ready.as_user(ready.a.reception) as actor:
        reversed_payment = service().reverse_payment(
            actor=actor, payment_id=payment.sysid, reason="Pagamento em duplicidade", expected_revision=payment.revision
        )
        assert reversed_payment.status == "reversed"
        with pytest.raises(Conflict):
            service().reverse_payment(
                actor=actor, payment_id=payment.sysid, reason="x", expected_revision=reversed_payment.revision
            )
        detail = service().charge(actor=actor, charge_id=charge.sysid).charge
        assert (detail.status, detail.paid_total) == ("open", 0)
        (title,) = LedgerService().titles_for_source(
            actor=actor, table_key="med_finance.charge", record_id=charge.sysid
        )
        (settlement,) = LedgerService().settlements(actor=actor, title_id=title.sysid)
        assert title.status == "open" and settlement.reversal_entry_id is not None
        assert (
            service()
            .cancel_charge(actor=actor, charge_id=charge.sysid, reason="Desistência", expected_revision=detail.revision)
            .charge.status
            == "cancelled"
        )


def test_cancel_with_a_payment_is_refused(ready):
    charge = charge_of(ready)
    open_desk(ready)
    pay(ready, charge, 1000, "p1")
    with ready.as_user(ready.a.reception) as actor:
        current = service().charge(actor=actor, charge_id=charge.sysid).charge
        with pytest.raises(Conflict) as error:
            service().cancel_charge(actor=actor, charge_id=charge.sysid, reason="x", expected_revision=current.revision)
    assert error.value.code == "has_payments"
