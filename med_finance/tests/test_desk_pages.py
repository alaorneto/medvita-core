"""The desk's short paths (#132): receipt after paying, fields by method, open charges, filters and reports."""

from __future__ import annotations

import html as markup
from datetime import timedelta

from django.utils import timezone

from ..service_api import ChargeItemInput, FinanceService
from .helpers import new_patient
from .test_views import assert_safe, client_for, ready, url

__all__ = ["ready"]


def _charge(ready, patient, key, *, due_date=None, confirm=True, amount=20000):
    with ready.as_user(ready.a.reception) as actor:
        return (
            FinanceService()
            .create_charge(
                actor=actor,
                patient_id=patient.sysid,
                items=(ChargeItemInput(description="Consulta", unit_amount=amount),),
                due_date=due_date,
                confirm=confirm,
                idempotency_key=key,
            )
            .charge
        )


def _open_session(ready):
    with ready.as_user(ready.a.reception) as actor:
        FinanceService().open_session(actor=actor, idempotency_key="session")


def _pay(client, ready, charge, **values):
    data = {"method": "pix", "amount": "200,00", "revision": charge.revision, "idempotency_key": "pay", **values}
    return client.post(url(ready, "charge_action", charge.sysid, "pay"), data)


def test_paying_opens_the_receipt_with_print_first(ready):
    patient = new_patient(ready)
    charge = _charge(ready, patient, "pay")
    _open_session(ready)
    client = client_for(ready.a.reception)
    response = _pay(client, ready, charge)
    with ready.as_user(ready.a.reception) as actor:
        (receipt,) = FinanceService().receipts(actor=actor, charge_id=charge.sysid).items
    assert response.status_code == 302
    assert response["Location"] == url(ready, "receipt", receipt.sysid)
    page = assert_safe(client.get(response["Location"]))
    printing = url(ready, "receipt_print", receipt.sysid)
    assert f'<a class="btn btn-primary" href="{printing}">Imprimir recibo</a>' in page
    assert page.count("btn-primary") == 1
    assert url(ready, "charge", charge.sysid) in page  # Back to the charge, for a partial payment.
    assert "Pagamento recebido e recibo emitido." in page


def test_payment_fields_without_script_and_server_validation(ready):
    patient = new_patient(ready)
    charge = _charge(ready, patient, "fields")
    _open_session(ready)
    client = client_for(ready.a.reception)
    page = assert_safe(client.get(url(ready, "charge", charge.sysid)))
    # Without the script every field is on the page, none hidden; the script only folds them.
    assert 'name="installments"' in page and 'name="authorization_code"' in page
    assert 'data-payment-only="credit_card"' in page and 'data-payment-only="debit_card credit_card"' in page
    assert " hidden" not in page.split('id="pay-heading"')[1].split("</form>")[0]
    assert "med_finance/med_finance.js" in page
    # Negative: installments outside the credit card are refused by the server, with what was typed.
    refused = _pay(client, ready, charge, installments="3", authorization_code="AB12")
    text = refused.content.decode()
    assert refused.status_code == 400 and "Só o cartão de crédito é parcelado." in text and 'value="AB12"' in text
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().payments(actor=actor, charge_id=charge.sysid) == ()
    # The script does not send a folded field: no installments is a single one.
    assert _pay(client, ready, charge, idempotency_key="folded").status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (payment,) = FinanceService().payments(actor=actor, charge_id=charge.sysid)
    assert payment.installments == 1 and payment.authorization_code == ""


def test_the_desk_lists_the_charges_open_until_today(ready):
    patient = new_patient(ready)
    today = timezone.localdate()
    due_today = _charge(ready, patient, "today")
    overdue = _charge(ready, patient, "overdue", due_date=today - timedelta(days=3))
    later = _charge(ready, patient, "later", due_date=today + timedelta(days=5))
    draft = _charge(ready, patient, "draft", confirm=False)
    paid = _charge(ready, patient, "paid")
    _open_session(ready)
    with ready.as_user(ready.a.reception) as actor:
        FinanceService().register_payment(
            actor=actor,
            charge_id=paid.sysid,
            method="cash",
            amount=paid.total,
            expected_revision=paid.revision,
            idempotency_key="paid",
        )
    page = assert_safe(client_for(ready.a.reception).get(url(ready, "desk")))
    listed = page.split("Contas em aberto até hoje")[1]
    assert due_today.code in listed and overdue.code in listed
    assert later.code not in listed and draft.code not in listed and paid.code not in listed
    query = markup.escape(f"status=outstanding&due_to={today.isoformat()}")
    assert f"{url(ready, 'charges')}?{query}" in page


def test_charges_filters_and_a_filter_without_result(ready):
    patient = new_patient(ready)
    today = timezone.localdate()
    overdue = _charge(ready, patient, "overdue", due_date=today - timedelta(days=40))
    current = _charge(ready, patient, "current")
    draft = _charge(ready, patient, "draft", confirm=False)
    client = client_for(ready.a.reception)
    outstanding = assert_safe(client.get(url(ready, "charges") + "?status=outstanding"))
    assert overdue.code in outstanding and current.code in outstanding and draft.code not in outstanding
    assert '<option value="outstanding" selected>' in outstanding and 'href="?"' in outstanding
    ranged = assert_safe(
        client.get(
            url(ready, "charges")
            + f"?due_from={(today - timedelta(days=60)).isoformat()}&due_to={(today - timedelta(days=31)).isoformat()}"
        )
    )
    assert overdue.code in ranged and current.code not in ranged
    # Negative: a filter that finds nothing says so and offers to clear it.
    nothing = assert_safe(client.get(url(ready, "charges") + "?status=paid"))
    assert "Nenhuma conta com estes filtros." in nothing and "Limpar" in nothing
    assert overdue.code not in nothing
    assert "Nenhuma conta com estes filtros." not in assert_safe(client.get(url(ready, "charges")))
    assert client.get(url(ready, "charges") + "?due_from=ontem").status_code == 404
    assert client.get(url(ready, "charges") + "?status=lost").status_code == 404


def test_receivables_buckets_link_to_their_charges(ready):
    patient = new_patient(ready)
    today = timezone.localdate()
    overdue = _charge(ready, patient, "overdue", due_date=today - timedelta(days=40))
    current = _charge(ready, patient, "current")
    client = client_for(ready.a.reception)
    page = assert_safe(client.get(url(ready, "receivables")))
    query = markup.escape(
        "status=outstanding"
        f"&due_from={(today - timedelta(days=60)).isoformat()}&due_to={(today - timedelta(days=31)).isoformat()}"
    )
    link = f"{url(ready, 'charges')}?{query}"
    assert link in page
    assert "61–90 dias</a>" not in page  # An empty bucket has nothing to open.
    listed = assert_safe(client.get(markup.unescape(link)))
    assert overdue.code in listed and current.code not in listed


def test_daily_report_walks_day_by_day_and_prints_without_navigation(ready):
    client = client_for(ready.a.reception)
    day = timezone.localdate() - timedelta(days=10)
    page = assert_safe(client.get(url(ready, "daily") + f"?date={day.isoformat()}"))
    assert f'href="?date={(day - timedelta(days=1)).isoformat()}" rel="prev"' in page
    assert f'href="?date={(day + timedelta(days=1)).isoformat()}" rel="next"' in page
    assert 'class="day-nav med-finance-no-print' in page and 'class="filter-bar med-finance-no-print"' in page
    assert '<article class="print-page">' in page and "data-print hidden" in page
    assert client.get(url(ready, "daily") + "?date=amanha").status_code == 404


def test_a_charge_with_several_lines_without_script(ready):
    patient = new_patient(ready)
    client = client_for(ready.a.reception)
    address = url(ready, "charge_new") + f"?patient={patient.sysid}"
    table = assert_safe(client.get(address))
    assert 'class="segmented"' in table and "mode=free" in table and 'name="item-0-code"' in table
    free = url(ready, "charge_new") + f"?patient={patient.sysid}&mode=free"
    assert 'name="item-0-description"' in assert_safe(client.get(free))
    typed = {
        "patient": patient.sysid,
        "mode": "free",
        "rows": "1",
        "idempotency_key": "lines",
        "item-0-description": "Curativo",
        "item-0-unit_amount": "80,00",
        "item-0-quantity": "1",
        "payer_name": "",
    }
    # "Acrescentar item" shows one more line and keeps what was typed; nothing is created.
    more = client.post(free, {**typed, "add_row": "1"})
    page = more.content.decode()
    assert more.status_code == 200 and 'name="item-1-description"' in page and 'value="Curativo"' in page
    assert 'name="rows" value="2"' in page and "error-summary" not in page
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().charges(actor=actor, patient_id=patient.sysid).items == ()
    # Negative: no line filled in is refused.
    empty = client.post(free, {**typed, "item-0-description": "", "item-0-unit_amount": ""})
    assert empty.status_code == 400 and "Informe ao menos um item." in empty.content.decode()
    # Two lines and a blank one: the blank line is left out.
    created = client.post(
        free,
        {
            **typed,
            "rows": "3",
            "item-1-description": "Material",
            "item-1-unit_amount": "20,50",
            "item-1-quantity": "2",
            "item-2-quantity": "1",
        },
    )
    assert created.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (charge,) = FinanceService().charges(actor=actor, patient_id=patient.sysid).items
        detail = FinanceService().charge(actor=actor, charge_id=charge.sysid)
    assert [item.description for item in detail.items] == ["Curativo", "Material"]
    assert charge.total == 8000 + 2 * 2050
