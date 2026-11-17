"""Registries of the patient page: codes of the calling app only, no silent replacement (no database)."""

import pytest

from ...extension import (
    PATIENT_SECTIONS,
    PatientSection,
    SetupStep,
    isolated_registries,
    register_patient_data_provider,
    register_patient_section,
    register_retention_guard,
    register_setup_step,
    register_timeline_provider,
)


def provider(**kwargs):
    return ()


def test_codes_must_belong_to_the_calling_app(subtests):
    with isolated_registries():
        for name, call in (
            ("other app", lambda: register_timeline_provider("med_scheduling.items", provider)),
            ("no dot", lambda: register_retention_guard("noapp", provider)),
            ("uppercase", lambda: register_patient_data_provider("med_patients.Bad", provider)),
            ("section of another app", lambda: register_patient_section(PatientSection("other.x", "X", "x"))),
        ):
            with subtests.test(name), pytest.raises(ValueError):
                call()


def test_same_contribution_twice_is_accepted_another_one_is_refused():
    section = PatientSection("med_patients.extra", "Extra", "med_patients:list", order=5)
    with isolated_registries():
        register_patient_section(section)
        register_patient_section(section)
        assert dict(PATIENT_SECTIONS.all())["med_patients.extra"] is section
        with pytest.raises(ValueError):
            register_patient_section(PatientSection("med_patients.extra", "Outra", "med_patients:list"))
    assert "med_patients.extra" not in dict(PATIENT_SECTIONS.all())


def test_wrong_types_are_refused(subtests):
    with isolated_registries():
        for name, call in (
            ("section", lambda: register_patient_section("med_patients.x")),
            ("step", lambda: register_setup_step({"code": "med_patients.x"})),
            ("provider", lambda: register_timeline_provider("med_patients.x", "not callable")),
        ):
            with subtests.test(name), pytest.raises(TypeError):
                call()
        assert register_setup_step(SetupStep("med_patients.x", "X", "x", lambda **kw: True)).code == "med_patients.x"
