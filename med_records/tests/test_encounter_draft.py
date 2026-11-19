"""Draft encounters: only the author writes them, every reader of the archive sees them, content is redacted."""

import json

import pytest

from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.service_api.audit import AuditService

from ..service_api import RecordsService
from .helpers import book_arrived, new_patient, open_chart, prepare, register_doctor, save, start

SECRET = "dor torácica há três dias"


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    return clinic


@pytest.fixture
def chart(ready):
    return open_chart(ready, new_patient(ready))


def test_start_save_and_read(ready, chart):
    draft = start(ready, chart)
    assert draft.header.code.startswith("E") and not draft.header.signed and draft.writable
    assert start(ready, chart).header.sysid == draft.header.sysid
    saved = save(ready, draft, "med_records.anamnesis", (("chief_complaint", SECRET),))
    saved = save(ready, saved, "med_records.vitals", (("systolic", "120"), ("temperature", "36,5")))
    assert saved.header.revision > draft.header.revision
    with ready.as_user(ready.a.doctor) as doctor:
        read = RecordsService().encounter(actor=doctor, encounter_id=draft.header.sysid)
        assert [section.section_type for section in read.sections] == ["med_records.anamnesis", "med_records.vitals"]
        assert json.loads(read.sections[1].data_json) == {"systolic": 120, "temperature": "36.5"}
        (header,) = RecordsService().encounters(actor=doctor, chart_id=chart.sysid).items
        assert header.sysid == draft.header.sysid
        assert RecordsService().chart(actor=doctor, chart_id=chart.sysid).last_entry_at is not None
    replaced = save(ready, saved, "med_records.vitals", (("systolic", 130),))
    assert len(replaced.sections) == 2


def test_only_the_author_writes_but_readers_read(ready, chart):
    draft = start(ready, chart)
    with ready.as_user(ready.a.admin) as admin:
        assert RecordsService().encounter(actor=admin, encounter_id=draft.header.sysid).writable is False
        with pytest.raises(Forbidden):
            RecordsService().save_section(
                actor=admin,
                encounter_id=draft.header.sysid,
                section_type="med_records.free_text",
                text="x",
                expected_revision=draft.header.revision,
            )
        with pytest.raises(Forbidden):
            RecordsService().discard_draft(
                actor=admin, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
            )
    with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
        RecordsService().encounter(actor=actor, encounter_id=draft.header.sysid)
    with ready.as_user(ready.b.doctor, ready.org_b) as outsider, pytest.raises(NotFound):
        RecordsService().encounter(actor=outsider, encounter_id=draft.header.sysid)


def test_cas_validation_and_discard(ready, chart):
    draft = start(ready, chart)
    save(ready, draft, "med_records.free_text", text="primeiro")
    with pytest.raises(Conflict) as error:
        save(ready, draft, "med_records.free_text", text="segundo")
    assert error.value.code == "stale_revision"
    current = save(ready, draft, "med_records.free_text", text="x", expected_revision=draft.header.revision + 1)
    for section_type, data in (("med_records.nope", ()), ("med_records.vitals", (("systolic", 999),))):
        with pytest.raises(InvalidInput):
            save(ready, current, section_type, data)
    with ready.as_user(ready.a.doctor) as doctor:
        removed = RecordsService().remove_section(
            actor=doctor,
            encounter_id=draft.header.sysid,
            section_id=current.sections[0].sysid,
            expected_revision=current.header.revision,
        )
        assert removed.sections == ()
        RecordsService().discard_draft(
            actor=doctor, encounter_id=draft.header.sysid, expected_revision=removed.header.revision
        )
        with pytest.raises(NotFound):
            RecordsService().encounter(actor=doctor, encounter_id=draft.header.sysid)


def test_clinical_content_is_redacted_in_the_audit(ready, chart):
    draft = save(ready, start(ready, chart), "med_records.anamnesis", (("chief_complaint", SECRET),), SECRET)
    with ready.as_user(ready.a.admin) as admin:
        entries = (
            AuditService()
            .history(actor=admin, table_key="med_records.encountersection", record_id=draft.sections[0].sysid)
            .items
        )
    values = " ".join(str(value) for entry in entries for change in entry.changes for value in (change.old, change.new))
    assert entries and SECRET not in values and "REDACTED" in values


def test_start_from_an_appointment(ready, chart):
    professional = register_doctor(ready)
    patient_id = chart.patient_id
    from applications.med_patients.service_api import PatientService

    with ready.as_user(ready.a.reception) as actor:
        patient = PatientService().summary(actor=actor, patient_id=patient_id)
    appointment = book_arrived(ready, patient, professional)
    draft = start(ready, chart, key="attend", appointment_id=appointment.sysid)
    assert draft.header.appointment_id == appointment.sysid
    with ready.as_user(ready.a.reception) as actor:
        current = SchedulingService().appointment(actor=actor, appointment_id=appointment.sysid).appointment
    assert current.status == "in_progress"
    other_chart = open_chart(ready, new_patient(ready, full_name="Outra Pessoa"))
    with pytest.raises(InvalidInput):
        start(ready, other_chart, key="wrong", appointment_id=appointment.sysid)
    with pytest.raises(NotFound):
        start(ready, chart, key="missing", appointment_id="00000000-0000-0000-0000-000000000009")
