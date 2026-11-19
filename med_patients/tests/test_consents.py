"""Consents by purpose: granted, revoked, the term attached and the purposes registered by apps."""

import io

import pytest
from django.test import override_settings

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.service_api.files import FileService
from skeleton.testing.events import capture_events

from ..extension import ConsentPurpose, isolated_registries, register_consent_purpose
from ..service_api import PatientService
from .helpers import new_patient, setup_registry

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def ready(clinic, tmp_path):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    storage = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(tmp_path / "files"), "base_url": None},
    }
    from django.conf import settings

    with override_settings(STORAGES={**settings.STORAGES, "skeleton_files": storage}):
        yield clinic


def service():
    return PatientService()


def grant(clinic, patient, key="c1", user=None):
    with clinic.as_user(user or clinic.a.reception) as actor:
        return service().grant_consent(
            actor=actor,
            patient_id=patient.sysid,
            purpose="med_patients.contact",
            collected_via="paper",
            term_version="v1",
            idempotency_key=key,
        )


def test_grant_revoke_and_grant_again(ready):
    patient = new_patient(ready)
    with capture_events() as events:
        consent = grant(ready, patient)
    assert [dict(event.data) for event in events] == [
        {"patient": str(patient.sysid), "purpose": "med_patients.contact", "status": "granted"}
    ]
    with ready.as_user(ready.a.reception) as actor:
        assert service().has_consent(actor=actor, patient_id=patient.sysid, purpose="med_patients.contact")
        with pytest.raises(Conflict) as error:
            service().grant_consent(
                actor=actor,
                patient_id=patient.sysid,
                purpose="med_patients.contact",
                collected_via="paper",
                idempotency_key="c2",
            )
        assert error.value.code == "already_granted"
        revoked = service().revoke_consent(actor=actor, consent_id=consent.sysid, expected_revision=1)
        assert revoked.status == "revoked" and revoked.revoked_at is not None
        assert not service().has_consent(actor=actor, patient_id=patient.sysid, purpose="med_patients.contact")
        with pytest.raises(Conflict):
            service().revoke_consent(actor=actor, consent_id=consent.sysid, expected_revision=2)
    again = grant(ready, patient, key="c3")
    with ready.as_user(ready.a.reception) as actor:
        history = service().consents(actor=actor, patient_id=patient.sysid)
    assert [row.sysid for row in history] == [again.sysid, consent.sysid]


def test_grant_is_idempotent_and_validated(ready, subtests):
    patient = new_patient(ready)
    assert grant(ready, patient).sysid == grant(ready, patient).sysid
    with ready.as_user(ready.a.reception) as actor:
        for name, arguments in (
            ("unknown purpose", {"purpose": "other_app.anything", "collected_via": "paper"}),
            ("unknown way", {"purpose": "med_patients.contact", "collected_via": "telepathy"}),
        ):
            with subtests.test(name), pytest.raises(InvalidInput):
                service().grant_consent(actor=actor, patient_id=patient.sysid, idempotency_key=name, **arguments)
    with ready.as_user(ready.a.finance) as actor, pytest.raises(Forbidden):
        service().grant_consent(
            actor=actor,
            patient_id=patient.sysid,
            purpose="med_patients.contact",
            collected_via="paper",
            idempotency_key="f",
        )


def test_term_attachment_follows_the_registry(ready, subtests):
    patient = new_patient(ready)
    consent = grant(ready, patient)
    with ready.as_user(ready.a.reception) as actor:
        attachment = FileService().attach(
            actor=actor,
            table_key="med_patients.consent",
            record_id=consent.sysid,
            filename="termo.pdf",
            stream=io.BytesIO(PDF),
            content_type="application/pdf",
        )
    with subtests.test("who reads the registry downloads"), ready.as_user(ready.a.finance) as actor:
        assert FileService().download_url(actor=actor, attachment_id=attachment.sysid)
    with subtests.test("who only reads cannot attach"), ready.as_user(ready.a.finance) as actor:
        with pytest.raises(Forbidden):
            FileService().attach(
                actor=actor,
                table_key="med_patients.consent",
                record_id=consent.sysid,
                filename="x.pdf",
                stream=io.BytesIO(PDF),
            )
    with subtests.test("organization B never downloads"), ready.as_user(ready.b.admin, ready.org_b) as actor:
        with pytest.raises(NotFound):
            FileService().download_url(actor=actor, attachment_id=attachment.sysid)


def test_purposes_of_disabled_apps_are_hidden(ready):
    with isolated_registries():
        register_consent_purpose(ConsentPurpose("med_patients.reminders", "Lembretes"))
        with ready.as_user(ready.a.reception) as actor:
            codes = [purpose.code for purpose in service().consent_purposes(actor=actor)]
        assert codes == ["med_patients.contact", "med_patients.reminders"]
        with pytest.raises(ValueError):
            register_consent_purpose(ConsentPurpose("med_scheduling.reminders", "De outra app"))
        with pytest.raises(ValueError):
            register_consent_purpose(ConsentPurpose("med_patients.reminders", "Outro texto"))
        with ready.app_disabled("med_patients"), ready.as_user(ready.a.reception) as actor:
            from skeleton.service_api import Unavailable

            with pytest.raises(Unavailable):
                service().consent_purposes(actor=actor)
