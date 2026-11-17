"""REST API of the patients app: authorization by the registry, revision in If-Match, no system fields."""

import json

import pytest
from django.test import Client
from django.urls import reverse

from .helpers import new_patient, setup_registry


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    return clinic


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def api(clinic, name, *args, organization=None):
    return reverse(f"med_patients_api:{name}", args=((organization or clinic.org_a).pk, *args))


def test_create_read_search_and_patch(ready):
    client = client_for(ready.a.reception)
    created = client.post(
        api(ready, "patients"),
        data=json.dumps({"full_name": "Ana API", "birth_date": "1990-02-03"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-1",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["code"] == "P000001" and created["ETag"] == '"1"'
    again = client.post(
        api(ready, "patients"),
        data=json.dumps({"full_name": "Ana API"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-1",
    )
    assert again.json()["sysid"] == body["sysid"]
    found = client.get(api(ready, "patients") + "?q=ana").json()["results"]
    assert [item["sysid"] for item in found] == [body["sysid"]]
    patient = api(ready, "patient", body["sysid"])
    assert client.get(patient).json()["birth_date"] == "1990-02-03"
    missing = client.patch(patient, data=json.dumps({"city": "X"}), content_type="application/json")
    assert missing.status_code == 400
    patched = client.patch(
        patient, data=json.dumps({"city": "Natal"}), content_type="application/json", HTTP_IF_MATCH='"1"'
    )
    assert patched.status_code == 200 and patched.json()["city"] == "Natal" and patched["ETag"] == '"2"'
    stale = client.patch(
        patient, data=json.dumps({"city": "Natal 2"}), content_type="application/json", HTTP_IF_MATCH='"1"'
    )
    assert stale.status_code == 409


def test_system_fields_are_refused(ready, subtests):
    client = client_for(ready.a.reception)
    patient = new_patient(ready)
    for field in ("organization", "registry", "code", "status", "processing_restricted"):
        with subtests.test(field):
            response = client.patch(
                api(ready, "patient", patient.sysid),
                data=json.dumps({field: "x"}),
                content_type="application/json",
                HTTP_IF_MATCH='"1"',
            )
            assert response.status_code == 400


def test_authorization_and_isolation(ready):
    patient = new_patient(ready)
    assert client_for(ready.b.reception).get(api(ready, "patient", patient.sysid)).status_code == 404
    finance = client_for(ready.a.finance)
    assert finance.get(api(ready, "patient", patient.sysid)).status_code == 200
    forbidden = finance.patch(
        api(ready, "patient", patient.sysid),
        data=json.dumps({"city": "X"}),
        content_type="application/json",
        HTTP_IF_MATCH='"1"',
    )
    assert forbidden.status_code == 403
    assert finance.get(api(ready, "guardians", patient.sysid)).json() == {"results": []}
    with ready.app_disabled("med_patients"):
        assert client_for(ready.a.reception).get(api(ready, "patients")).status_code in (403, 404, 503)
