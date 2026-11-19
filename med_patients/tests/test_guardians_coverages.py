"""Guardians and coverages: derived from the patient, two hops to the registry."""

from datetime import date
from itertools import count

import pytest

from skeleton.service_api import Conflict, Forbidden, NotFound
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import assert_cas_conflict, build_service_scenario

from ..models import Patient, PatientCoverage, PatientGuardian, PatientRegistry
from ..service_api import CoverageInput, GuardianInput, PatientService
from .helpers import new_patient, setup_registry


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    return clinic


def service():
    return PatientService()


@pytest.mark.parametrize("model", [PatientGuardian, PatientCoverage])
def test_rows_follow_the_registry(skeleton_db, model):
    open_app("med_patients")
    scenario = build_service_scenario(model, slug=f"rows-{model._meta.model_name}")
    numbers = count(1)

    def make_registry(*, organization, owner):
        registry = PatientRegistry(
            organization=organization, owner=owner, visibility="private", name=f"R{next(numbers)}"
        )
        registry.save()
        return registry

    def make_row(registry):
        patient = Patient(
            organization=registry.organization, registry=registry, code=f"P{next(numbers):06d}", full_name="Maria"
        )
        patient.save()
        if model is PatientGuardian:
            row = PatientGuardian(organization=registry.organization, patient=patient, name="Mãe")
        else:
            row = PatientCoverage(
                organization=registry.organization, patient=patient, insurer_name="X", card_number="1"
            )
        row.save()
        return row

    assert_derived_access_contract(child_model=model, make_anchor=make_registry, make_child=make_row, scenario=scenario)


def test_guardians_and_coverages_disappear_and_return_with_the_patient(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        guardian = service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="Mãe"))
        service().add_coverage(
            actor=actor, patient_id=patient.sysid, data=CoverageInput(insurer_name="Plano", card_number="123")
        )
        service().delete(actor=actor, patient_id=patient.sysid, expected_revision=patient.revision)
        with pytest.raises(NotFound):
            service().guardians(actor=actor, patient_id=patient.sysid)
        with pytest.raises(NotFound):
            service().update_guardian(
                actor=actor, guardian_id=guardian.sysid, data=GuardianInput(name="X"), expected_revision=1
            )
        service().restore(actor=actor, patient_id=patient.sysid, expected_revision=patient.revision + 1)
        assert [row.name for row in service().guardians(actor=actor, patient_id=patient.sysid)] == ["Mãe"]
        assert [row.card_number for row in service().coverages(actor=actor, patient_id=patient.sysid)] == ["123"]


def test_one_primary_coverage(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        first = service().add_coverage(
            actor=actor,
            patient_id=patient.sysid,
            data=CoverageInput(insurer_name="A", card_number="1", is_primary=True),
        )
        second = service().add_coverage(
            actor=actor,
            patient_id=patient.sysid,
            data=CoverageInput(insurer_name="B", card_number="2", is_primary=True),
        )
        rows = service().coverages(actor=actor, patient_id=patient.sysid)
        assert [(row.sysid, row.is_primary) for row in rows] == [(second.sysid, True), (first.sysid, False)]
        service().update_coverage(
            actor=actor,
            coverage_id=first.sysid,
            data=CoverageInput(insurer_name="A", card_number="1", is_primary=True),
            expected_revision=2,
        )
        rows = service().coverages(actor=actor, patient_id=patient.sysid)
        assert [row.sysid for row in rows if row.is_primary] == [first.sysid]


def test_minor_without_legal_representative_needs_a_guardian(ready):
    today = date.today()
    minor = new_patient(ready, birth_date=today.replace(year=today.year - 10))
    adult = new_patient(ready, full_name="Adulto", birth_date=date(1980, 1, 1))
    with ready.as_user(ready.a.reception) as actor:
        assert service().get(actor=actor, patient_id=minor.sysid).needs_guardian
        assert not service().get(actor=actor, patient_id=adult.sysid).needs_guardian
        service().add_guardian(
            actor=actor, patient_id=minor.sysid, data=GuardianInput(name="Mãe", is_legal_representative=True)
        )
        assert not service().get(actor=actor, patient_id=minor.sysid).needs_guardian


def test_writes_need_update_on_the_registry_and_use_cas(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        guardian = service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="Pai"))
    with ready.as_user(ready.a.finance) as actor:
        assert [row.sysid for row in service().guardians(actor=actor, patient_id=patient.sysid)] == [guardian.sysid]
        with pytest.raises(Forbidden):
            service().add_guardian(actor=actor, patient_id=patient.sysid, data=GuardianInput(name="X"))
        with pytest.raises(Forbidden):
            service().remove_guardian(actor=actor, guardian_id=guardian.sysid, expected_revision=1)

    def rename(name):
        def call():
            with ready.as_user(ready.a.reception) as actor:
                return service().update_guardian(
                    actor=actor, guardian_id=guardian.sysid, data=GuardianInput(name=name), expected_revision=1
                )

        return call

    assert assert_cas_conflict(rename("Pai Novo"), rename("Outro")).name == "Pai Novo"
    with ready.as_user(ready.b.reception, ready.org_b) as actor, pytest.raises(NotFound):
        service().guardians(actor=actor, patient_id=patient.sysid)
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict):
            service().remove_guardian(actor=actor, guardian_id=guardian.sysid, expected_revision=1)
        service().remove_guardian(actor=actor, guardian_id=guardian.sysid, expected_revision=2)
        assert service().guardians(actor=actor, patient_id=patient.sysid) == ()


def test_idempotent_additions(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.reception) as actor:
        data = GuardianInput(name="Mãe")
        one = service().add_guardian(actor=actor, patient_id=patient.sysid, data=data, idempotency_key="g1")
        two = service().add_guardian(actor=actor, patient_id=patient.sysid, data=data, idempotency_key="g1")
        assert one.sysid == two.sysid
        assert len(service().guardians(actor=actor, patient_id=patient.sysid)) == 1
