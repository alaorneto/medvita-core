"""The finance API with the access token of a native client (#61): the same answers as the session."""

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext

from ..service_api import FinanceService
from .helpers import add_price, new_patient, prepare


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    return clinic


def session(user):
    client = Client()
    client.force_login(user)
    return client


def api(ready, name, *args, organization=None):
    return reverse(f"med_finance_api:{name}", args=((organization or ready.org_a).pk, *args))


def post(client, address, body, **headers):
    return client.post(address, data=json.dumps(body), content_type="application/json", **headers)


def narrowed(native_clients, user, client_id, scopes):
    native_clients.register(client_id, scopes=scopes)
    return native_clients.client(user, scope="openid " + " ".join(scopes), client_id=client_id)


def assert_scope_refused(response):
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == gettext("O token não tem o escopo exigido.")


def open_desk(ready):
    with ready.as_user(ready.a.reception) as actor:
        FinanceService().open_session(actor=actor, idempotency_key="open")


def test_token_charges_and_receives_like_the_session(ready, native_clients):
    patient = new_patient(ready)
    open_desk(ready)
    token = native_clients.client(ready.a.reception)
    browser = session(ready.a.reception)
    assert token.get(api(ready, "price_items")).json() == browser.get(api(ready, "price_items")).json()
    body = {"patient": str(patient.sysid), "items": [{"code": "C1"}]}
    assert post(token, api(ready, "charges"), body).status_code == 400  # No Idempotency-Key.
    created = post(token, api(ready, "charges"), body, HTTP_IDEMPOTENCY_KEY="tok-1")
    assert created.status_code == 201, created.content
    charge = created.json()["charge"]
    assert created["ETag"] == f'"{charge["revision"]}"'
    assert post(token, api(ready, "charges"), body, HTTP_IDEMPOTENCY_KEY="tok-1").json() == created.json()
    detail = api(ready, "charge", charge["sysid"])
    assert token.get(detail).json() == browser.get(detail).json()
    payments = api(ready, "payments", charge["sysid"])
    payment = {"method": "pix", "amount": 25000}
    assert post(token, payments, payment, HTTP_IDEMPOTENCY_KEY="p").status_code == 400  # No If-Match.
    paid = post(token, payments, payment, HTTP_IDEMPOTENCY_KEY="p", HTTP_IF_MATCH=f'"{charge["revision"]}"')
    assert paid.status_code == 201, paid.content
    assert token.get(payments).json() == browser.get(payments).json()
    assert token.get(api(ready, "charges")).json() == browser.get(api(ready, "charges")).json()
    with ready.as_user(ready.a.reception) as actor:
        (receipt,) = FinanceService().receipts(actor=actor, charge_id=charge["sysid"]).items
    by_token = token.get(api(ready, "receipt", receipt.sysid))
    assert by_token.json() == browser.get(api(ready, "receipt", receipt.sysid)).json()
    assert by_token.json()["number"] == receipt.number


def test_methods_outside_token_methods_are_refused(ready, native_clients):
    token = native_clients.client(ready.a.reception)
    for method, url in (
        ("post", api(ready, "price_items")),
        ("delete", api(ready, "charges")),
        ("patch", api(ready, "charges")),
    ):
        response = getattr(token, method)(url)
        assert response.status_code == 403 and response.json()["code"] == "token_not_allowed", (method, url)


def test_scope_role_and_organization(ready, native_clients):
    patient = new_patient(ready)
    open_desk(ready)
    reader = narrowed(
        native_clients,
        ready.a.reception,
        "medvita-caixa",
        ("finance:read", "med_finance.pricelist:read", "med_finance.cashdesk:read"),
    )
    assert reader.get(api(ready, "price_items")).status_code == 200
    assert reader.get(api(ready, "charges")).status_code == 200
    body = {"patient": str(patient.sysid), "items": [{"code": "C1"}]}
    assert_scope_refused(post(reader, api(ready, "charges"), body, HTTP_IDEMPOTENCY_KEY="r-1"))
    patients_only = narrowed(native_clients, ready.a.reception, "medvita-patients", ("patients:read",))
    assert_scope_refused(patients_only.get(api(ready, "charges")))
    # The doctor does not read the desk: the broad token carries finance:read and still sees nothing.
    created = post(native_clients.client(ready.a.reception), api(ready, "charges"), body, HTTP_IDEMPOTENCY_KEY="c")
    charge = api(ready, "charge", created.json()["charge"]["sysid"])
    assert native_clients.client(ready.a.doctor).get(charge).status_code == 404
    assert session(ready.a.doctor).get(charge).status_code == 404
    outsider = native_clients.client(ready.b.reception)
    assert outsider.get(charge).status_code == 404
