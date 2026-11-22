"""The records API with the access token of a native client (#61): read only, and the trail names the client."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext

from ..models import AccessLog
from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare, save, start

BODY = "Paciente com quadro gripal, afastamento de 2 dias."


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def session(user):
    client = Client()
    client.force_login(user)
    return client


def api(ready, name, *args, organization=None):
    return reverse(f"med_records_api:{name}", args=((organization or ready.org_a).pk, *args))


def narrowed(native_clients, user, client_id, scopes):
    native_clients.register(client_id, scopes=scopes)
    return native_clients.client(user, scope="openid " + " ".join(scopes), client_id=client_id)


def trail(ready, target_id):
    with ready.as_user(ready.a.doctor):
        return set(AccessLog.objects.filter(target_id=target_id).values_list("origin", "client_id"))


def document(ready, chart):
    with ready.as_user(ready.a.doctor) as doctor:
        return RecordsService().draft_document(
            actor=doctor,
            chart_id=chart.sysid,
            idempotency_key="doc",
            kind="med_records.certificate",
            body=BODY,
        )


def test_token_reads_like_the_session_and_the_trail_names_the_client(ready, native_clients):
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    encounter = save(ready, start(ready, chart), "med_records.free_text", text="segredo clínico")
    token = native_clients.client(ready.a.doctor)
    browser = session(ready.a.doctor)
    charts = api(ready, "charts") + f"?patient={patient.sysid}"
    by_token = token.get(charts)
    assert by_token.status_code == 200 and by_token["Cache-Control"] == "no-store"
    assert by_token.json() == browser.get(charts).json()
    listed = api(ready, "encounters", chart.sysid)
    assert token.get(listed).json() == browser.get(listed).json()
    assert trail(ready, encounter.header.sysid) == set()  # Lists carry headers only: nothing is recorded.
    detail = api(ready, "encounter", encounter.header.sysid)
    read = token.get(detail)
    assert read.status_code == 200 and read.json()["sections"][0]["text"] == "segredo clínico"
    assert trail(ready, encounter.header.sysid) == {(AccessLog.Origin.NATIVE_CLIENT, native_clients.client_id)}
    assert browser.get(detail).json() == read.json()
    assert trail(ready, encounter.header.sysid) == {
        (AccessLog.Origin.NATIVE_CLIENT, native_clients.client_id),
        (AccessLog.Origin.WEB, ""),
    }
    token.get(detail)  # The same client within five minutes: recorded once.
    with ready.as_user(ready.a.doctor):
        assert AccessLog.objects.filter(target_id=encounter.header.sysid).count() == 2


def test_document_detail_by_token(ready, native_clients):
    chart = open_chart(ready, new_patient(ready))
    info = document(ready, chart)
    read = native_clients.client(ready.a.doctor).get(api(ready, "document", info.header.sysid))
    assert read.status_code == 200, read.content
    assert read.json() == session(ready.a.doctor).get(api(ready, "document", info.header.sysid)).json()
    assert (AccessLog.Origin.NATIVE_CLIENT, native_clients.client_id) in trail(ready, info.header.sysid)


def test_writing_is_always_refused_to_a_token(ready, native_clients):
    chart = open_chart(ready, new_patient(ready))
    encounter = start(ready, chart)
    token = native_clients.client(ready.a.doctor)
    for method in ("post", "patch", "put", "delete"):
        for url in (api(ready, "charts"), api(ready, "encounter", encounter.header.sysid)):
            response = getattr(token, method)(url)
            assert response.status_code == 403 and response.json()["code"] == "token_not_allowed", (method, url)


def test_scope_role_and_organization(ready, native_clients):
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    encounter = start(ready, chart)
    reader = narrowed(native_clients, ready.a.doctor, "medvita-records", ("records:read", "med_records.archive:read"))
    assert reader.get(api(ready, "encounter", encounter.header.sysid)).status_code == 200
    assert reader.get(api(ready, "encounters", chart.sysid)).status_code == 200
    assert {origin for origin, _client in trail(ready, encounter.header.sysid)} == {AccessLog.Origin.NATIVE_CLIENT}
    patients_only = narrowed(native_clients, ready.a.doctor, "medvita-patients", ("patients:read",))
    refused = patients_only.get(api(ready, "encounter", encounter.header.sysid))
    assert refused.status_code == 403 and refused.json()["detail"] == gettext("O token não tem o escopo exigido.")
    # Reception does not read clinical content: the broad token carries records:read and still gets 404.
    reception = native_clients.client(ready.a.reception)
    assert reception.get(api(ready, "encounter", encounter.header.sysid)).status_code == 404
    assert reception.get(api(ready, "charts") + f"?patient={patient.sysid}").json()["results"] == []
    outsider = native_clients.client(ready.b.doctor)
    assert outsider.get(api(ready, "encounter", encounter.header.sysid)).status_code == 404
    with ready.as_user(ready.a.doctor):  # Only the narrowed reader was recorded: refusals leave no trail.
        assert AccessLog.objects.filter(target_id=encounter.header.sysid).count() == 1
