"""Read-only REST API of the records app: headers in lists, content in the detail, no-store, isolation."""

import pytest
from django.test import Client
from django.urls import reverse

from ..models import AccessLog
from .helpers import new_patient, open_chart, prepare, save, start


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def api(ready, name, *args, organization=None):
    return reverse(f"med_records_api:{name}", args=((organization or ready.org_a).pk, *args))


def test_charts_encounters_and_detail(ready):
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    draft = save(ready, start(ready, chart), "med_records.free_text", text="segredo clínico")
    doctor = client_for(ready.a.doctor)
    charts = doctor.get(api(ready, "charts") + f"?patient={patient.sysid}")
    assert charts.status_code == 200 and charts["Cache-Control"] == "no-store"
    assert [item["sysid"] for item in charts.json()["results"]] == [str(chart.sysid)]
    listed = doctor.get(api(ready, "encounters", chart.sysid)).json()["results"]
    assert [item["code"] for item in listed] == [draft.header.code] and "segredo" not in str(listed)
    detail = doctor.get(api(ready, "encounter", draft.header.sysid))
    assert detail.json()["sections"][0]["text"] == "segredo clínico"
    with ready.as_user(ready.a.doctor):
        assert AccessLog.objects.filter(target_id=draft.header.sysid, action="view_encounter").exists()
    assert doctor.get(api(ready, "charts")).status_code == 400
    assert doctor.post(api(ready, "charts"), {}).status_code == 405


def test_reception_other_organization_and_disabled_app(ready):
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    draft = start(ready, chart)
    reception = client_for(ready.a.reception)
    assert reception.get(api(ready, "encounter", draft.header.sysid)).status_code == 404
    assert reception.get(api(ready, "encounters", chart.sysid)).status_code == 404
    assert reception.get(api(ready, "charts") + f"?patient={patient.sysid}").json()["results"] == []
    outsider = client_for(ready.b.doctor)
    assert outsider.get(api(ready, "encounter", draft.header.sysid, organization=ready.org_b)).status_code == 404
    with ready.app_disabled("med_records"):
        assert client_for(ready.a.doctor).get(api(ready, "encounter", draft.header.sysid)).status_code in (
            403,
            404,
            503,
        )
