"""Pages and REST API of the finance app: the desk flow, receipts, authorization and safe HTML."""

import json
import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from ..service_api import FinanceService
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
        {"patient": patient.sysid, "code": "C1", "quantity": 1, "idempotency_key": "c"},
    )
    assert created.status_code == 302
    charge_id = created["Location"].rstrip("/").split("/")[-1]
    with ready.as_user(ready.a.reception) as actor:
        charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
    page = assert_safe(client.get(url(ready, "charge", charge_id)))
    assert "R$ 250,00" in page
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
        assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
        receipts = FinanceService().receipts(actor=actor, charge_id=charge_id).items
        session = FinanceService().current_session(actor=actor)
    assert charge.status == "paid" and len(receipts) == 2
    printed = assert_safe(client.get(url(ready, "receipt_print", receipts[0].sysid)))
    assert "Maria Caixa" in printed and "não substitui documento fiscal" in printed
    assert (
        client.post(
            url(ready, "session_movement", session.sysid),
            {"kind": "withdrawal", "amount": "50,00", "reason": "Banco", "idempotency_key": "w"},
        ).status_code
        == 302
    )
    closed = client.post(
        url(ready, "session_close", session.sysid),
        {"counted_amount": "140,00", "note": "", "revision": session.revision},
    )
    assert closed.status_code == 302
    report = assert_safe(client.get(closed["Location"]))
    assert "R$ 150,00" in report and "-R$ 10,00" in report
    assert_safe(client.get(url(ready, "charges")))
    assert_safe(client.get(url(ready, "prices")))


def test_collect_and_patient_tab(ready):
    patient = new_patient(ready)
    appointment = book(ready, patient)
    client = client_for(ready.a.reception)
    page = client.get(reverse("med_scheduling:appointment", args=(ready.org_a.pk, appointment.sysid)))
    assert url(ready, "collect", appointment.sysid) in page.content.decode()
    response = client.get(url(ready, "collect", appointment.sysid))
    assert response.status_code == 302 and "/charges/" in response["Location"]
    assert client.get(url(ready, "collect", appointment.sysid))["Location"] == response["Location"]
    assert "R$ 250,00" in assert_safe(client.get(url(ready, "patient_section", patient.sysid)))


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
