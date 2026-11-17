"""The read trail, attachments of the chart and encounter, and the patient page contributions."""

import io

import pytest
from django.test import Client

from applications.med_patients.service_api import PatientService
from skeleton.service_api import Conflict, Forbidden, NotFound
from skeleton.service_api.access import AccessService

from ..models import AccessLog
from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare, save, start

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def chart(ready):
    return open_chart(ready, new_patient(ready))


def service():
    return RecordsService()


def signed(ready, chart):
    draft = save(ready, start(ready, chart), "med_records.free_text", text="x")
    with ready.as_user(ready.a.doctor) as doctor:
        return service().sign_encounter(
            actor=doctor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
        )


def test_reads_are_recorded_once_per_person_and_window(ready, chart):
    encounter = signed(ready, chart)
    for _ in range(2):
        with ready.as_user(ready.a.doctor) as doctor:
            service().encounter(actor=doctor, encounter_id=encounter.header.sysid)
    with ready.as_user(ready.a.admin) as admin:
        service().encounter(actor=admin, encounter_id=encounter.header.sysid)
        entries = service().access_log(actor=admin, chart_id=chart.sysid).items
    readers = [(entry.actor_id, entry.action) for entry in entries if entry.action == "view_encounter"]
    assert sorted(readers) == sorted([(ready.a.doctor.pk, "view_encounter"), (ready.a.admin.pk, "view_encounter")])
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises(Forbidden):
        service().access_log(actor=doctor, chart_id=chart.sysid)
    with ready.as_user(ready.a.admin):
        row = AccessLog.objects.filter(chart_id=chart.sysid).first()
        row.action = "export"
        with pytest.raises(Exception, match="(?i)cannot be changed|immutable"):
            row.save()


def test_attachments_of_chart_and_encounter(ready, chart):
    with ready.as_user(ready.a.doctor) as doctor:
        exam = service().attach_to_chart(
            actor=doctor,
            chart_id=chart.sysid,
            filename="exame.pdf",
            stream=io.BytesIO(PDF),
            content_type="application/pdf",
        )
        assert [item.sysid for item in service().attachments(actor=doctor, chart_id=chart.sysid)] == [exam.sysid]
        url = service().attachment_url(actor=doctor, attachment_id=exam.sysid, chart_id=chart.sysid)
    client = Client()
    client.force_login(ready.a.doctor)
    assert client.get(url).status_code == 200
    with ready.as_user(ready.a.admin) as admin:
        (archive,) = service().archives(actor=admin)
        for action in ("read", "update"):
            AccessService().revoke_record_access(
                actor=admin,
                table_key="med_records.archive",
                record_id=archive.sysid,
                action=action,
                group_id=ready.a.groups["professionals"],
            )
    assert client.get(url).status_code == 404
    outsider = Client()
    outsider.force_login(ready.b.doctor)
    assert outsider.get(url).status_code == 404


def test_signed_encounter_takes_no_attachment(ready, chart):
    encounter = signed(ready, chart)
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Conflict):
            service().attach_to_encounter(
                actor=doctor,
                encounter_id=encounter.header.sysid,
                filename="x.pdf",
                stream=io.BytesIO(PDF),
                content_type="application/pdf",
            )
    draft = start(ready, chart, key="second")
    with ready.as_user(ready.a.doctor) as doctor:
        attached = service().attach_to_encounter(
            actor=doctor,
            encounter_id=draft.header.sysid,
            filename="x.pdf",
            stream=io.BytesIO(PDF),
            content_type="application/pdf",
        )
        assert service().attachments(actor=doctor, encounter_id=draft.header.sysid)[0].sysid == attached.sysid
    with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
        service().attachments(actor=actor, chart_id=chart.sysid)


def test_patient_page_contributions(ready, chart):
    signed(ready, chart)
    with ready.as_user(ready.a.doctor) as doctor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=doctor, patient_id=chart.patient_id)]
        timeline = PatientService().timeline(actor=doctor, patient_id=chart.patient_id).items
        report = PatientService().patient_sections(actor=doctor)
    assert "med_records.chart" in tabs and "med_records.chart" in [row.code for row in report]
    assert "Atendimento registrado" in [entry.title for entry in timeline]
    with ready.as_user(ready.a.reception) as actor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=chart.patient_id)]
        timeline = PatientService().timeline(actor=actor, patient_id=chart.patient_id).items
    assert "med_records.chart" not in tabs
    assert not [entry for entry in timeline if entry.source == "med_records.records"]
