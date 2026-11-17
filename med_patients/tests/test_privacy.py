"""Data subject rights: the report, the processing restriction and the anonymization."""

import logging

import pytest
from django.test import Client
from django.urls import reverse

from skeleton.service_api import Conflict, Forbidden

from ..extension import DATA_PROVIDERS, RETENTION_GUARDS, isolated_registries
from ..service_api import GuardianInput, PatientService
from .helpers import new_patient, setup_registry

CPF = "52998224725"


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    with isolated_registries():
        yield clinic


def service():
    return PatientService()


def test_privacy_operations_need_manage_access(ready, subtests):
    patient = new_patient(ready, cpf=CPF)
    with ready.as_user(ready.a.reception) as actor:
        for name, call in (
            ("report", lambda: service().data_report(actor=actor, patient_id=patient.sysid)),
            (
                "restrict",
                lambda: service().restrict_processing(
                    actor=actor, patient_id=patient.sysid, restricted=True, expected_revision=1
                ),
            ),
            ("anonymize", lambda: service().anonymize(actor=actor, patient_id=patient.sysid, expected_revision=1)),
        ):
            with subtests.test(name), pytest.raises(Forbidden):
                call()


def test_data_report_gathers_the_sections_of_active_apps(ready, caplog):
    patient = new_patient(ready, full_name="Titular Exemplo", cpf=CPF)
    with ready.as_user(ready.a.reception) as actor:
        service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="Mãe"))
    DATA_PROVIDERS.add("med_patients.extra", lambda *, actor, patient_id: (("Consultas", "3"),), caller=None)

    def broken(**kwargs):
        raise RuntimeError("down")

    DATA_PROVIDERS.add("med_patients.broken", broken, caller=None)
    with caplog.at_level(logging.INFO), ready.as_user(ready.a.admin) as admin:
        report = service().data_report(actor=admin, patient_id=patient.sysid)
    assert report.patient.cpf == CPF and [row.name for row in report.guardians] == ["Mãe"]
    sections = {section.code: section for section in report.sections}
    assert sections["med_patients.extra"].lines == (("Consultas", "3"),)
    assert not sections["med_patients.broken"].available
    logged = " ".join(str(record.__dict__) for record in caplog.records if "data_report" in record.getMessage())
    assert str(patient.sysid) in logged and "Titular Exemplo" not in logged and CPF not in logged


def test_restricted_patient_is_found_but_does_not_change(ready):
    patient = new_patient(ready, full_name="Restrito")
    with ready.as_user(ready.a.admin) as admin:
        restricted = service().restrict_processing(
            actor=admin, patient_id=patient.sysid, restricted=True, expected_revision=1
        )
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict) as error:
            service().update(
                actor=actor, patient_id=patient.sysid, changes=(("city", "X"),), expected_revision=restricted.revision
            )
        assert error.value.code == "processing_restricted"
        assert [item.sysid for item in service().search(actor=actor, query="restrito").items] == [patient.sysid]
        with pytest.raises(Conflict):
            service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="X"))
    with ready.as_user(ready.a.admin) as admin:
        lifted = service().restrict_processing(
            actor=admin, patient_id=patient.sysid, restricted=False, expected_revision=restricted.revision
        )
    with ready.as_user(ready.a.reception) as actor:
        service().update(
            actor=actor, patient_id=patient.sysid, changes=(("city", "X"),), expected_revision=lifted.revision
        )


def test_anonymize_respects_guards_and_erases_identification(ready):
    patient = new_patient(ready, full_name="Nome Antigo", cpf=CPF, phone="11988887777", city="Recife")
    with ready.as_user(ready.a.reception) as actor:
        service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="Mãe Antiga"))
    RETENTION_GUARDS.add("med_patients.keep", lambda *, patient_id: "Prontuário dentro da guarda legal.", caller=None)
    with ready.as_user(ready.a.admin) as admin:
        with pytest.raises(Conflict) as error:
            service().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=1)
        assert error.value.code == "retention" and "guarda legal" in str(error.value.detail)
    RETENTION_GUARDS.restore({})
    with ready.as_user(ready.a.admin) as admin:
        done = service().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=1)
        assert done.full_name == f"Paciente anonimizado {patient.code}" and done.anonymized_at is not None
        assert (done.cpf, done.phone, done.city, done.status) == ("", "", "", "inactive")
        assert service().guardians(actor=admin, patient_id=patient.sysid) == ()
    with ready.as_user(ready.a.reception) as actor:
        for query in ("nome antigo", CPF, "988887777"):
            assert service().search(actor=actor, query=query).items == ()
        with pytest.raises(Conflict):
            service().update(
                actor=actor, patient_id=patient.sysid, changes=(("city", "X"),), expected_revision=done.revision
            )


def test_privacy_page(ready):
    patient = new_patient(ready, cpf=CPF)
    admin = Client()
    admin.force_login(ready.a.admin)
    page = reverse("med_patients:privacy", args=(ready.org_a.pk, patient.sysid))
    assert admin.get(page).status_code == 200
    reception = Client()
    reception.force_login(ready.a.reception)
    assert reception.get(page).status_code == 404
    detail = reception.get(reverse("med_patients:detail", args=(ready.org_a.pk, patient.sysid))).content.decode()
    assert "Privacidade" not in detail
    wrong = admin.post(
        reverse("med_patients:anonymize", args=(ready.org_a.pk, patient.sysid)), {"revision": 1, "confirm_code": "P9"}
    )
    assert wrong.status_code == 302
    with ready.as_user(ready.a.admin) as actor:
        assert service().get(actor=actor, patient_id=patient.sysid).anonymized_at is None
