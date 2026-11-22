"""The patients API with the access token of a native client (#61): the same answers as the session."""

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext

from .helpers import new_patient, setup_registry


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    return clinic


def session(user):
    client = Client()
    client.force_login(user)
    return client


def api(clinic, name, *args, organization=None):
    return reverse(f"med_patients_api:{name}", args=((organization or clinic.org_a).pk, *args))


def post(client, url, body, **headers):
    return client.post(url, data=json.dumps(body), content_type="application/json", **headers)


def patch(client, url, body, **headers):
    return client.patch(url, data=json.dumps(body), content_type="application/json", **headers)


def test_token_answers_like_the_session(ready, native_clients):
    token = native_clients.client(ready.a.reception)
    browser = session(ready.a.reception)
    created = post(token, api(ready, "patients"), {"full_name": "Ana Token"}, HTTP_IDEMPOTENCY_KEY="tok-1")
    assert created.status_code == 201, created.content
    assert created["ETag"] == '"1"'
    replayed = post(token, api(ready, "patients"), {"full_name": "Ana Token"}, HTTP_IDEMPOTENCY_KEY="tok-1")
    assert replayed.json()["sysid"] == created.json()["sysid"]
    patient = api(ready, "patient", created.json()["sysid"])
    by_token, by_session = token.get(patient), browser.get(patient)
    assert by_token.status_code == by_session.status_code == 200
    assert by_token.json() == by_session.json() and by_token["ETag"] == by_session["ETag"]
    found = token.get(api(ready, "patients") + "?q=ana").json()
    assert found == browser.get(api(ready, "patients") + "?q=ana").json()
    assert [item["sysid"] for item in found["results"]] == [created.json()["sysid"]]
    assert patch(token, patient, {"city": "Natal"}).status_code == 400  # No If-Match.
    patched = patch(token, patient, {"city": "Natal"}, HTTP_IF_MATCH='"1"')
    assert patched.status_code == 200 and patched.json()["city"] == "Natal" and patched["ETag"] == '"2"'
    assert patch(token, patient, {"city": "Natal 2"}, HTTP_IF_MATCH='"1"').status_code == 409
    for name in ("guardians", "coverages"):
        url = api(ready, name, created.json()["sysid"])
        assert token.get(url).json() == browser.get(url).json() == {"results": []}


def test_methods_outside_token_methods_are_refused(ready, native_clients):
    patient = new_patient(ready)
    token = native_clients.client(ready.a.reception)
    for method, url in (
        ("delete", api(ready, "patient", patient.sysid)),
        ("post", api(ready, "guardians", patient.sysid)),
        ("put", api(ready, "patient", patient.sysid)),
    ):
        response = getattr(token, method)(url)
        assert response.status_code == 403 and response.json()["code"] == "token_not_allowed", (method, url)


def narrowed(native_clients, user, client_id, scopes):
    """A client the operator limited to ``scopes`` (``native_client register --scope``), asking for them."""
    native_clients.register(client_id, scopes=scopes)
    return native_clients.client(user, scope="openid " + " ".join(scopes), client_id=client_id)


def assert_scope_refused(response):
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == gettext("O token não tem o escopo exigido.")


# A narrowed client needs the app's named scope (the gate of the API) and the table scope of the
# container the service authorizes (the core's single point where a scope applies).
READER = ("patients:read", "med_patients.patientregistry:read")


def test_scope_narrows_and_never_widens(ready, native_clients):
    patient = new_patient(ready)
    reader = narrowed(native_clients, ready.a.reception, "medvita-read", READER)
    detail = reader.get(api(ready, "patient", patient.sysid))
    assert detail.status_code == 200 and detail.json()["writable"] is False
    assert reader.get(api(ready, "patients")).status_code == 200
    assert_scope_refused(post(reader, api(ready, "patients"), {"full_name": "Sem escopo"}, HTTP_IDEMPOTENCY_KEY="r-1"))
    assert_scope_refused(patch(reader, api(ready, "patient", patient.sysid), {"city": "X"}, HTTP_IF_MATCH='"1"'))
    # The table scope alone does not open the API, and another app's scope does not either.
    table_only = narrowed(native_clients, ready.a.reception, "medvita-table", READER[1:])
    assert_scope_refused(table_only.get(api(ready, "patients")))
    agenda = narrowed(native_clients, ready.a.reception, "medvita-agenda", ("scheduling:read",))
    assert_scope_refused(agenda.get(api(ready, "patient", patient.sysid)))
    # Finance only reads the registry: a broad token carries patients:write and still cannot change it.
    finance = native_clients.client(ready.a.finance)
    assert finance.get(api(ready, "patient", patient.sysid)).status_code == 200
    denied = patch(finance, api(ready, "patient", patient.sysid), {"city": "X"}, HTTP_IF_MATCH='"1"')
    assert (
        denied.status_code
        == patch(
            session(ready.a.finance), api(ready, "patient", patient.sysid), {"city": "X"}, HTTP_IF_MATCH='"1"'
        ).status_code
        == 403
    )


def test_other_organization_is_not_found(ready, native_clients):
    patient = new_patient(ready)
    outsider = native_clients.client(ready.b.reception)
    assert outsider.get(api(ready, "patient", patient.sysid)).status_code == 404
    assert outsider.get(api(ready, "patients")).status_code == 404
    assert outsider.get(api(ready, "patient", patient.sysid, organization=ready.org_b)).status_code == 404
