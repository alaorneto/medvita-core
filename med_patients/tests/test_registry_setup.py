"""Patient registry: setup by the administrator, grants to groups and derived access of the patient table."""

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import assert_service_contract, build_service_scenario

from ..models import Patient, PatientRegistry
from ..service_api import PatientService


def setup_registry(clinic, side=None, *, key="setup-1", readers=("finance",)):
    side = side or clinic.a
    with clinic.as_user(side.admin, side.organization) as admin:
        return PatientService().setup(
            actor=admin,
            name="Pacientes da clínica",
            writer_group_ids=(side.groups["reception"], side.groups["professionals"]),
            reader_group_ids=tuple(side.groups[name] for name in readers),
            idempotency_key=key,
        )


def test_service_contract():
    assert_service_contract(PatientService)


def test_setup_creates_the_default_registry_and_shares_it(clinic, subtests):
    registry = setup_registry(clinic)
    assert registry.is_default and registry.writable
    service = PatientService()
    for user, writable in ((clinic.a.reception, True), (clinic.a.doctor, True), (clinic.a.finance, False)):
        with subtests.test(user=user.email), clinic.as_user(user) as actor:
            (seen,) = service.registries(actor=actor)
            assert (seen.sysid, seen.writable) == (registry.sysid, writable)
    with subtests.test("the other organization sees nothing"), clinic.as_user(clinic.b.admin, clinic.org_b) as actor:
        assert service.registries(actor=actor) == ()


def test_setup_is_idempotent_and_only_once(clinic):
    first = setup_registry(clinic)
    again = setup_registry(clinic)
    assert again.sysid == first.sysid
    with pytest.raises(Conflict) as error:
        setup_registry(clinic, key="setup-2")
    assert error.value.code == "already_set_up"
    with clinic.as_user(clinic.a.admin) as admin:
        assert len(PatientService().registries(actor=admin)) == 1


def test_setup_requires_the_access_manager(clinic):
    with clinic.as_user(clinic.a.reception) as actor, pytest.raises(Forbidden):
        PatientService().setup(actor=actor, name="X", idempotency_key="k")
    with clinic.as_user(clinic.a.admin) as admin:
        assert PatientService().registries(actor=admin) == ()


def test_setup_validates_its_input(clinic, subtests):
    service = PatientService()
    cases = {
        "empty name": {"name": " ", "idempotency_key": "k"},
        "empty key": {"name": "X", "idempotency_key": ""},
        "groups not a tuple": {"name": "X", "idempotency_key": "k", "writer_group_ids": ["x"]},
        "foreign group": {"name": "X", "idempotency_key": "k", "writer_group_ids": (clinic.b.groups["reception"],)},
    }
    for name, arguments in cases.items():
        with subtests.test(name), clinic.as_user(clinic.a.admin) as admin:
            with pytest.raises((InvalidInput, Forbidden, Conflict)):
                service.setup(actor=admin, **arguments)


def test_patient_follows_the_registry(skeleton_db):
    from skeleton.testing.applications import open_app

    open_app("med_patients")
    scenario = build_service_scenario(Patient, slug="patients-derived")
    counter = iter(range(1, 1000))

    def make_registry(*, organization, owner):
        registry = PatientRegistry(
            organization=organization, owner=owner, visibility="private", name=f"R{next(counter)}"
        )
        registry.save()
        return registry

    def make_patient(registry):
        patient = Patient(
            organization=registry.organization, registry=registry, code=f"P{next(counter):06d}", full_name="Maria"
        )
        patient.save()
        return patient

    assert_derived_access_contract(
        child_model=Patient, make_anchor=make_registry, make_child=make_patient, scenario=scenario
    )
