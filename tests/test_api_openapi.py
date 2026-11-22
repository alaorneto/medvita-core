"""The OpenAPI of the suite's REST views (#61): what a token sees, and the schemas match the real JSON.

The core builds ``/api/v1/openapi.json`` from the ``openapi`` declaration of each view and filters
it by the caller: a token sees only the methods of ``token_methods`` and the operations of its
scopes. The shapes come from the DTOs (``api_support.dto_schema``); here a real response of every
kind is compared with its schema, key by key, so a DTO and its documentation cannot drift apart.
"""

import json

import pytest
from django.test import Client

from applications.med_finance.tests.helpers import add_price, setup_finance
from applications.med_patients.service_api import PatientInput, PatientService
from applications.med_records.tests.helpers import open_chart, setup_archive
from applications.med_scheduling.tests.booking import at, prepare

APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")
WRITES = {
    ("med_patients", "patients/", "post"),
    ("med_patients", "patients/{patient_id}/", "patch"),
    ("med_scheduling", "appointments/", "post"),
    ("med_scheduling", "appointments/{appointment_id}/{transition}/", "post"),
    ("med_finance", "charges/", "post"),
    ("med_finance", "charges/{charge_id}/payments/", "post"),
}


@pytest.fixture
def ready(clinic):
    prepared = prepare(clinic)  # Patients, the practice, a schedule and a patient in A.
    setup_archive(clinic)
    setup_finance(clinic, clinic.a)
    add_price(clinic, "C1", 25000)
    return prepared


def operations(document):
    """``{(app, path under the app, method)}`` of the suite's routes in an OpenAPI document."""
    found = set()
    for path, item in document["paths"].items():
        for app in APPS:
            prefix = f"/api/v1/o/{{organization_id}}/apps/{app}/"
            if path.startswith(prefix):
                found |= {(app, path.removeprefix(prefix), method) for method in item}
    return found


def schema_of(client):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200, response.content
    return response.json()


def test_a_token_sees_only_what_it_may_call(ready, native_clients):
    browser = Client()
    browser.force_login(ready.a.reception)
    by_session = operations(schema_of(browser))
    assert WRITES <= by_session
    assert ("med_records", "encounters/{encounter_id}/", "get") in by_session
    broad = schema_of(native_clients.client(ready.a.reception))
    assert operations(broad) == by_session  # Every view of the suite declares its methods and scopes.
    patient_path = broad["paths"]["/api/v1/o/{organization_id}/apps/med_patients/patients/"]
    assert {"bearerAuth": []} in patient_path["get"]["security"]
    native_clients.register("medvita-read", scopes=("patients:read", "med_patients.patientregistry:read"))
    reader = native_clients.client(
        ready.a.reception, scope="openid patients:read med_patients.patientregistry:read", client_id="medvita-read"
    )
    assert operations(schema_of(reader)) == {
        ("med_patients", "patients/", "get"),
        ("med_patients", "patients/{patient_id}/", "get"),
        ("med_patients", "patients/{patient_id}/guardians/", "get"),
        ("med_patients", "patients/{patient_id}/coverages/", "get"),
    }


def keys_match(schema, value, document, where="$"):
    """The property names of ``schema`` are exactly the keys of ``value``, recursively."""
    if "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    if "allOf" in schema:
        for part in schema["allOf"]:
            if part.get("properties"):
                keys_match(
                    {**part, "additionalProperties": False}, {k: value[k] for k in part["properties"]}, document, where
                )
        return
    if "anyOf" in schema:
        if value is None:
            return
        schema = next(part for part in schema["anyOf"] if part.get("type") != "null")
    if isinstance(value, dict) and "properties" in schema:
        assert set(value) == set(schema["properties"]), (where, sorted(set(value) ^ set(schema["properties"])))
        for name, item in value.items():
            keys_match(schema["properties"][name], item, document, f"{where}.{name}")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            keys_match(schema["items"], item, document, f"{where}[{index}]")


def test_the_declared_schemas_match_the_responses(ready, native_clients):
    with ready.as_user(ready.a.reception) as actor:
        PatientService().create(actor=actor, data=PatientInput(full_name="Paciente Schema"))
    token = native_clients.client(ready.a.reception)
    doctor = native_clients.client(ready.a.doctor)
    chart = open_chart(ready, ready.patient)
    org = ready.org_a.pk
    booked = token.post(
        f"/api/v1/o/{org}/apps/med_scheduling/appointments/",
        data=json.dumps(
            {
                "schedule": str(ready.schedule.sysid),
                "patient": str(ready.patient.sysid),
                "appointment_type": str(ready.kind.sysid),
                "starts_at": at(ready, 9).isoformat(),
            }
        ),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="schema",
    ).json()
    charge = token.post(
        f"/api/v1/o/{org}/apps/med_finance/charges/",
        data=json.dumps({"patient": str(ready.patient.sysid), "items": [{"code": "C1"}], "confirm": False}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="schema",
    )
    calls = [
        (token, "med_patients", "patients/", ""),
        (token, "med_patients", f"patients/{ready.patient.sysid}/", ""),
        (token, "med_patients", f"patients/{ready.patient.sysid}/guardians/", ""),
        (token, "med_scheduling", "schedules/", ""),
        (token, "med_scheduling", f"schedules/{ready.schedule.sysid}/slots/", f"?start={ready.monday:%Y-%m-%d}"),
        (token, "med_scheduling", "appointments/", ""),
        (token, "med_scheduling", f"appointments/{booked['sysid']}/", ""),
        (token, "med_finance", "price-items/", ""),
        (token, "med_finance", "charges/", ""),
        (doctor, "med_records", "charts/", f"?patient={ready.patient.sysid}"),
        (doctor, "med_records", f"charts/{chart.sysid}/encounters/", ""),
    ]
    assert charge.status_code == 201, charge.content
    calls.append((token, "med_finance", f"charges/{charge.json()['charge']['sysid']}/", ""))
    browser = Client()
    browser.force_login(ready.a.doctor)
    document = schema_of(browser)
    templates = document["paths"]
    for client, app, path, query in calls:
        response = client.get(f"/api/v1/o/{org}/apps/{app}/{path}{query}")
        assert response.status_code == 200, (app, path, response.content)
        template = next(
            key
            for key in templates
            if key.startswith(f"/api/v1/o/{{organization_id}}/apps/{app}/")
            and _matches(key.removeprefix(f"/api/v1/o/{{organization_id}}/apps/{app}/"), path)
        )
        body = templates[template]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        keys_match(body, response.json(), document, f"{app}/{path}")


def _matches(template, path):
    parts, real = template.strip("/").split("/"), path.strip("/").split("/")
    return len(parts) == len(real) and all(a == b or a.startswith("{") for a, b in zip(parts, real, strict=True))
