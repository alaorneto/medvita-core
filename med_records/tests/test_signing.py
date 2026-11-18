"""Signing by seal: the author, a professional record, the seal contract, the event and the appointment."""

import pytest

from applications.med_patients.service_api import PatientService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict, Forbidden, NotFound
from skeleton.testing.sealing import assert_sealed_contract

from .. import service_api as records_api
from ..models import Encounter, EncounterSection
from ..service_api import RecordsService, seal_extra
from .helpers import book_arrived, new_patient, open_chart, prepare, register_doctor, save, start

SECRET = "suspeita de pneumonia"


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def chart(ready):
    return open_chart(ready, new_patient(ready))


def sign(ready, info, user=None):
    with ready.as_user(user or ready.a.doctor) as actor:
        return RecordsService().sign_encounter(
            actor=actor, encounter_id=info.header.sysid, expected_revision=info.header.revision
        )


def test_seal_contract(ready, chart):
    keys = iter(range(100))

    doctor = ready.a.doctor  # acting() opens the doctor's context around make_record and seal.

    def make_record():
        service = RecordsService()
        draft = service.start_encounter(actor=doctor, chart_id=chart.sysid, idempotency_key=f"c{next(keys)}")
        service.save_section(
            actor=doctor,
            encounter_id=draft.header.sysid,
            section_type="med_records.free_text",
            text=SECRET,
            expected_revision=draft.header.revision,
        )
        return Encounter.objects.get(pk=draft.header.sysid)

    def seal(record):
        RecordsService().sign_encounter(actor=doctor, encounter_id=record.pk, expected_revision=record.revision)
        return Encounter.objects.get(pk=record.pk)

    def make_child(record):
        EncounterSection(
            organization_id=record.organization_id, encounter=record, section_type="med_records.plan", text="x"
        ).save()

    assert_sealed_contract(
        Encounter,
        make_record=make_record,
        seal=seal,
        acting=lambda: ready.as_user(ready.a.doctor),
        foreign=lambda: ready.as_user(ready.b.doctor, ready.org_b),
        make_child=make_child,
        extra=seal_extra,
    )


def test_sign_publishes_and_freezes(ready, chart, monkeypatch):
    draft = save(ready, start(ready, chart), "med_records.anamnesis", (("chief_complaint", SECRET),), SECRET)
    published = []
    from skeleton.service_api.events import EventService

    original = EventService.publish

    def spy(self, **kwargs):
        published.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(EventService, "publish", spy)
    signed = sign(ready, draft)
    assert signed.header.signed and len(signed.header.seal_digest) == 64
    assert signed.header.author_name == "Dra. Ana" and signed.header.author_council == "CRM-SP 123456"
    (event,) = published
    assert event["event_type"] == "med_records.encounter_signed"
    assert dict(event["data"])["seal_digest"] == signed.header.seal_digest
    assert SECRET not in repr(event)
    with pytest.raises(Conflict) as error:
        save(ready, signed, "med_records.free_text", text="mudança", expected_revision=signed.header.revision)
    assert error.value.code == "signed"
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Conflict):
            RecordsService().discard_draft(
                actor=doctor, encounter_id=signed.header.sysid, expected_revision=signed.header.revision
            )
        check = RecordsService().verify_encounter(actor=doctor, encounter_id=signed.header.sysid)
        assert check.signed and check.valid
        with pytest.raises(Exception, match="(?i)seal"):
            row = EncounterSection.objects.get(pk=signed.sections[0].sysid)
            row.text = "adulterado"
            row.save()

    with ready.as_user(ready.a.doctor):
        tampered = dict(seal_extra(Encounter.objects.get(pk=signed.header.sysid)))
    tampered["sections"] = [{**tampered["sections"][0], "text": "adulterado"}]
    monkeypatch.setattr(records_api, "seal_extra", lambda encounter: tampered)
    with ready.as_user(ready.a.doctor) as doctor:
        assert RecordsService().verify_encounter(actor=doctor, encounter_id=signed.header.sysid).valid is False


def test_sign_needs_content_author_and_professional(ready, chart):
    empty = start(ready, chart, key="empty")
    with pytest.raises(Conflict) as error:
        sign(ready, empty)
    assert error.value.code == "empty"
    draft = save(ready, start(ready, chart, key="full"), "med_records.free_text", text="x")
    with pytest.raises(Forbidden):
        sign(ready, draft, user=ready.a.admin)
    with ready.as_user(ready.a.admin) as admin:
        draft_by_admin = RecordsService().start_encounter(actor=admin, chart_id=chart.sysid, idempotency_key="adm")
        draft_by_admin = RecordsService().save_section(
            actor=admin,
            encounter_id=draft_by_admin.header.sysid,
            section_type="med_records.free_text",
            text="x",
            expected_revision=draft_by_admin.header.revision,
        )
        with pytest.raises(Conflict) as error:
            RecordsService().sign_encounter(
                actor=admin,
                encounter_id=draft_by_admin.header.sysid,
                expected_revision=draft_by_admin.header.revision,
            )
        assert error.value.code == "professional_required"
        assert not RecordsService().encounter(actor=admin, encounter_id=draft_by_admin.header.sysid).header.signed


def test_signing_completes_the_appointment(ready, chart):
    with ready.as_user(ready.a.reception) as actor:
        patient = PatientService().summary(actor=actor, patient_id=chart.patient_id)
    appointment = book_arrived(ready, patient, register_doctor(ready))
    draft = save(
        ready, start(ready, chart, key="attend", appointment_id=appointment.sysid), "med_records.plan", text="x"
    )
    signed = sign(ready, draft)
    assert signed.appointment_completed
    with ready.as_user(ready.a.reception) as actor:
        assert SchedulingService().appointment(actor=actor, appointment_id=appointment.sysid).appointment.status == (
            "completed"
        )
        actions = SchedulingService().appointment_actions(actor=actor, appointment_id=appointment.sysid)
    assert "med_records.attend" not in [action.code for action in actions]


def test_addendum(ready, chart):
    draft = save(ready, start(ready, chart), "med_records.free_text", text="original")
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Conflict) as error:
            RecordsService().add_addendum(actor=doctor, encounter_id=draft.header.sysid, text="x", idempotency_key="a")
        assert error.value.code == "not_signed"
    signed = sign(ready, draft)
    with ready.as_user(ready.a.doctor) as doctor:
        addendum = RecordsService().add_addendum(
            actor=doctor, encounter_id=signed.header.sysid, text="correção", idempotency_key="a"
        )
        assert addendum.header.kind == "addendum" and addendum.header.amends_id == signed.header.sysid
        with pytest.raises(Conflict):
            RecordsService().add_addendum(
                actor=doctor, encounter_id=addendum.header.sysid, text="x", idempotency_key="b"
            )
    with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
        RecordsService().add_addendum(actor=actor, encounter_id=signed.header.sysid, text="x", idempotency_key="c")
    sign(ready, addendum)
    with ready.as_user(ready.a.doctor) as doctor:
        original = RecordsService().encounter(actor=doctor, encounter_id=signed.header.sysid)
        assert [item.sysid for item in original.addenda] == [addendum.header.sysid]
        assert RecordsService().verify_encounter(actor=doctor, encounter_id=signed.header.sysid).valid
