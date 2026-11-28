"""Pages and REST API of the finance app: the desk flow, receipts, authorization and safe HTML."""

import json
import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from ..service_api import FinanceService
from ..templatetags.med_finance_format import brl
from .helpers import add_price, book, new_patient, prepare

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
UNSAFE = re.compile(r"\sstyle=|\son[a-z]+=", re.IGNORECASE)
APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    return clinic


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_finance:{name}", args=((organization or ready.org_a).pk, *args))


def api(ready, name, *args, organization=None):
    return reverse(f"med_finance_api:{name}", args=((organization or ready.org_a).pk, *args))


def assert_safe(response):
    assert response.status_code == 200, response.status_code
    html = response.content.decode()
    assert not INLINE_SCRIPT.search(html), "inline script"
    assert not UNSAFE.search(html), "style= or on*= attribute"
    assert "·" in re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    return html


def test_pages_use_only_the_services():
    source = (APP_DIR / "views.py").read_text(encoding="utf-8")
    assert ".objects" not in source and "authorized_queryset" not in source


def test_desk_flow_through_the_pages(ready):
    patient = new_patient(ready, full_name="Maria Caixa")
    client = client_for(ready.a.reception)
    assert "Abrir o caixa" in assert_safe(client.get(url(ready, "desk")))
    assert (
        client.post(url(ready, "session_open"), {"opening_amount": "100,00", "idempotency_key": "o"}).status_code == 302
    )
    assert_safe(client.get(url(ready, "charge_new") + f"?patient={patient.sysid}"))
    created = client.post(
        url(ready, "charge_new") + f"?patient={patient.sysid}",
        {"patient": patient.sysid, "rows": 1, "item-0-code": "C1", "item-0-quantity": 1, "idempotency_key": "c"},
    )
    assert created.status_code == 302
    charge_id = created["Location"].rstrip("/").split("/")[-1]
    with ready.as_user(ready.a.reception) as actor:
        charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
    page = assert_safe(client.get(url(ready, "charge", charge_id)))
    assert brl(25000) in page  # #122: a non-breaking space after "R$".
    for method, amount, key in (("cash", "100,00", "p1"), ("pix", "150,00", "p2")):
        with ready.as_user(ready.a.reception) as actor:
            charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
        response = client.post(
            url(ready, "charge_action", charge_id, "pay"),
            {
                "method": method,
                "amount": amount,
                "installments": 1,
                "revision": charge.revision,
                "idempotency_key": key,
            },
        )
        assert response.status_code == 302 and "/receipts/" in response["Location"]  # #132: straight to the receipt.
    with ready.as_user(ready.a.reception) as actor:
        charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
        receipts = FinanceService().receipts(actor=actor, charge_id=charge_id).items
        session = FinanceService().current_session(actor=actor)
    assert charge.status == "paid" and len(receipts) == 2
    printed = assert_safe(client.get(url(ready, "receipt_print", receipts[0].sysid)))
    assert "Maria Caixa" in printed and "não substitui documento fiscal" in printed
    # #118: the printed receipt has its own title, the clinic's address and the receiver's signature line.
    assert "<h1" in printed and "Assinatura de quem recebeu" in printed and "Código de verificação" in printed
    assert (
        client.post(
            url(ready, "session_movement", session.sysid),
            {"kind": "withdrawal", "amount": "50,00", "reason": "Banco", "idempotency_key": "w"},
        ).status_code
        == 302
    )
    values = {"counted_amount": "140,00", "note": "", "revision": session.revision}
    # #119: the first POST shows expected, counted and difference; nothing is closed yet.
    asked = assert_safe(client.post(url(ready, "session_close", session.sysid), values))
    assert f"Esperado em dinheiro: {brl(15000)}" in asked
    assert "Faltam" in asked and 'name="confirmed"' in asked
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().current_session(actor=actor) is not None
    closed = client.post(url(ready, "session_close", session.sysid), {**values, "confirmed": "1"})
    assert closed.status_code == 302
    report = assert_safe(client.get(closed["Location"]))
    assert brl(15000) in report and brl(-1000) in report
    assert_safe(client.get(url(ready, "charges")))
    # #123: the filter lists every status of the model (draft too) and offers to clear an applied filter.
    listing = assert_safe(client.get(url(ready, "charges") + "?status=draft"))
    assert '<option value="draft" selected>' in listing and 'href="?"' in listing
    assert_safe(client.get(url(ready, "prices")))


def test_collect_and_patient_tab(ready):
    patient = new_patient(ready)
    appointment = book(ready, patient)
    client = client_for(ready.a.reception)
    page = client.get(reverse("med_scheduling:appointment", args=(ready.org_a.pk, appointment.sysid)))
    assert url(ready, "collect", appointment.sysid) in page.content.decode()
    # #131: "Receber" creates the charge by POST only; a GET answers 405 and creates nothing.
    assert client.get(url(ready, "collect", appointment.sysid)).status_code == 405
    with ready.as_user(ready.a.reception) as actor:
        assert not FinanceService().charges_for_origin(
            actor=actor, origin_app="med_scheduling", origin_key=str(appointment.sysid)
        )
    response = client.post(url(ready, "collect", appointment.sysid))
    assert response.status_code == 302 and "/charges/" in response["Location"]
    assert client.post(url(ready, "collect", appointment.sysid))["Location"] == response["Location"]
    assert brl(25000) in assert_safe(client.get(url(ready, "patient_section", patient.sysid)))


def test_who_sees_what(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        from ..service_api import ChargeItemInput

        charge = (
            FinanceService()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="c"
            )
            .charge
        )
    doctor = client_for(ready.a.doctor)
    assert doctor.get(url(ready, "charge", charge.sysid)).status_code == 404
    assert doctor.get(url(ready, "patient_section", patient.sysid)).status_code == 404
    assert "Nenhum caixa" in doctor.get(url(ready, "desk")).content.decode()
    outsider = client_for(ready.b.reception)
    assert outsider.get(url(ready, "charge", charge.sysid, organization=ready.org_b)).status_code == 404
    assert client_for(ready.a.reception).get(url(ready, "setup")).status_code == 404
    assert_safe(client_for(ready.a.admin).get(url(ready, "setup")))


def test_api(ready):
    patient = new_patient(ready)
    client = client_for(ready.a.reception)
    with ready.as_user(ready.a.reception) as actor:
        FinanceService().open_session(actor=actor, idempotency_key="o")
    assert [item["code"] for item in client.get(api(ready, "price_items")).json()["results"]] == ["C1"]
    body = {"patient": str(patient.sysid), "items": [{"code": "C1"}]}
    missing = client.post(api(ready, "charges"), data=json.dumps(body), content_type="application/json")
    assert missing.status_code == 400
    created = client.post(
        api(ready, "charges"), data=json.dumps(body), content_type="application/json", HTTP_IDEMPOTENCY_KEY="k"
    )
    assert created.status_code == 201, created.content
    charge = created.json()["charge"]
    assert charge["total"] == 25000
    bad = client.post(
        api(ready, "charges"),
        data=json.dumps({**body, "status": "paid"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="k2",
    )
    assert bad.status_code == 400
    paid = client.post(
        api(ready, "payments", charge["sysid"]),
        data=json.dumps({"method": "pix", "amount": 25000}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="p",
        HTTP_IF_MATCH=f'"{charge["revision"]}"',
    )
    assert paid.status_code == 201, paid.content
    assert client.get(api(ready, "charge", charge["sysid"])).json()["charge"]["status"] == "paid"
    with ready.as_user(ready.a.reception) as actor:
        (receipt,) = FinanceService().receipts(actor=actor, charge_id=charge["sysid"]).items
    assert client.get(api(ready, "receipt", receipt.sysid)).json()["number"] == receipt.number
    assert client_for(ready.a.doctor).get(api(ready, "charge", charge["sysid"])).status_code == 404
    outsider = client_for(ready.b.reception)
    assert outsider.get(api(ready, "charge", charge["sysid"], organization=ready.org_b)).status_code == 404
    with ready.app_disabled("med_finance"):
        assert client.get(api(ready, "charges")).status_code in (403, 404, 503)


def test_money_actions_ask_first(ready):
    """Cancelling a charge, reversing a payment, voiding a receipt and deactivating a price ask (#119)."""
    patient = new_patient(ready)
    client = client_for(ready.a.reception)
    with ready.as_user(ready.a.reception) as actor:
        from ..service_api import ChargeItemInput

        charge = (
            FinanceService()
            .create_charge(
                actor=actor,
                patient_id=patient.sysid,
                items=(ChargeItemInput(description="Consulta", unit_amount=20000),),
                idempotency_key="ask",
            )
            .charge
        )
    cancel = url(ready, "charge_action", charge.sysid, "cancel")
    asked = assert_safe(client.get(cancel))
    assert "Cancelar a conta" in asked and 'name="reason"' in asked
    assert client.get(url(ready, "charge_action", charge.sysid, "pay")).status_code == 405
    assert (
        client_for(ready.b.reception)
        .get(url(ready, "charge_action", charge.sysid, "cancel", organization=ready.org_b))
        .status_code
        == 404
    )
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().charge(actor=actor, charge_id=charge.sysid).charge.status != "cancelled"
    done = client.post(cancel, {"reason": "Lançada por engano", "revision": charge.revision})
    assert done.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().charge(actor=actor, charge_id=charge.sysid).charge.status == "cancelled"
    assert client.get(cancel).status_code == 404  # Nothing left to cancel.


def test_a_refused_payment_keeps_what_was_typed(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        from ..service_api import ChargeItemInput

        charge = (
            FinanceService()
            .create_charge(
                actor=actor,
                patient_id=patient.sysid,
                items=(ChargeItemInput(description="Consulta", unit_amount=20000),),
                idempotency_key="typed",
            )
            .charge
        )
        FinanceService().open_session(actor=actor, idempotency_key="typed-open")  # Receiving needs the desk open.
    client = client_for(ready.a.reception)
    response = client.post(
        url(ready, "charge_action", charge.sysid, "pay"),
        {"method": "pix", "amount": "duzentos", "installments": "1", "revision": charge.revision},
    )
    html = response.content.decode()
    assert response.status_code == 400 and 'value="duzentos"' in html and "Informe um valor em reais" in html
    assert "error-summary" in html


def test_the_patient_search_goes_by_post_and_never_into_the_address(ready):
    """#147: a name or a CPF is never in the URL; a ``q`` in the address searches nothing."""
    new_patient(ready, full_name="Maria Caixa Busca")
    client = client_for(ready.a.finance)
    found = assert_safe(client.post(url(ready, "charge_new"), {"form": "search", "q": "Caixa Busca"}))
    assert "Maria Caixa Busca" in found and not re.search(r'href="[^"]*q=', found)
    assert "Maria Caixa Busca" not in assert_safe(client.get(url(ready, "charge_new"), {"q": "Caixa Busca"}))
    # The search creates no charge.
    with ready.as_user(ready.a.finance) as actor:
        assert FinanceService().charges(actor=actor, page_size=5).items == ()
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(ready.a.finance)
    assert strict.post(url(ready, "charge_new"), {"form": "search", "q": "Maria"}).status_code == 403


def test_a_charge_with_the_desk_closed_offers_to_open_it_and_comes_back(ready):
    """#148: no receiving form while the desk is closed; opening it from the charge returns to the charge."""
    from ..service_api import ChargeItemInput

    patient = new_patient(ready, full_name="Maria Caixa Fechado")
    with ready.as_user(ready.a.reception) as actor:
        charge = (
            FinanceService()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="closed"
            )
            .charge
        )
    client = client_for(ready.a.reception)
    closed = assert_safe(client.get(url(ready, "charge", charge.sysid)))
    assert "O caixa está fechado." in closed and "Receber e emitir recibo" not in closed
    assert 'name="method"' not in closed and f'name="charge" value="{charge.sysid}"' in closed
    opened = client.post(
        url(ready, "session_open"),
        {"charge": charge.sysid, "opening_amount": "50,00", "idempotency_key": "from-charge"},
    )
    assert opened.status_code == 302 and opened["Location"] == url(ready, "charge", charge.sysid)
    with ready.as_user(ready.a.reception) as actor:
        assert FinanceService().current_session(actor=actor, desk_id=charge.desk_id) is not None
    open_page = assert_safe(client.get(url(ready, "charge", charge.sysid)))
    assert "O caixa está fechado." not in open_page and "Receber e emitir recibo" in open_page


@pytest.mark.parametrize("given", ["https://evil.example/x", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_opening_the_desk_goes_back_only_to_a_charge_it_can_read(ready, given):
    """#148: the return is built from a charge the service reads; anything else goes back to the desk."""
    client = client_for(ready.a.reception)
    response = client.post(url(ready, "session_open"), {"charge": given, "idempotency_key": f"o-{given[:8]}"})
    assert response.status_code == 302 and response["Location"] == url(ready, "desk")


def test_opening_the_desk_never_goes_back_to_a_charge_of_another_organization(ready):
    from ..service_api import ChargeItemInput

    add_price(ready, "C1", 25000, side=ready.b)
    patient = new_patient(ready, ready.b)
    with ready.as_user(ready.b.reception, ready.org_b) as actor:
        other = (
            FinanceService()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="b"
            )
            .charge
        )
    response = client_for(ready.a.reception).post(
        url(ready, "session_open"), {"charge": other.sysid, "idempotency_key": "cross"}
    )
    assert response.status_code == 302 and response["Location"] == url(ready, "desk")
