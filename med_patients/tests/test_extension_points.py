"""Timeline, sections, setup steps and retention guards with contributions of active apps."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from skeleton.service_api import Conflict, Forbidden

from ..extension import (
    PATIENT_SECTIONS,
    RETENTION_GUARDS,
    SETUP_STEPS,
    TIMELINE_PROVIDERS,
    PatientSection,
    SetupStep,
    TimelineEntry,
    isolated_registries,
)
from ..service_api import PatientService
from .helpers import new_patient, setup_registry

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    with isolated_registries(empty=True):
        yield clinic


def make_provider(source, minutes):
    """A provider whose items are at BASE + each minute, answering the window it is asked for."""

    def provider(*, actor, patient_id, before, limit):
        items = [
            TimelineEntry(at=BASE + timedelta(minutes=minute), source=source, kind="test", title=f"{source} {minute}")
            for minute in minutes
        ]
        items = [item for item in items if before is None or item.at <= before]
        return tuple(sorted(items, key=lambda item: item.at, reverse=True)[:limit])

    return provider


def walk(clinic, patient, page_size):
    titles, cursor = [], None
    with clinic.as_user(clinic.a.reception) as actor:
        while True:
            page = PatientService().timeline(actor=actor, patient_id=patient.sysid, cursor=cursor, page_size=page_size)
            titles += [item.title for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                return titles


def test_timeline_interleaves_and_pages_without_repeating(ready, subtests):
    patient = new_patient(ready)
    TIMELINE_PROVIDERS.add("med_patients.a", make_provider("med_patients.a", [1, 3, 5, 7, 9]), caller=None)
    TIMELINE_PROVIDERS.add("med_patients.b", make_provider("med_patients.b", [2, 3, 4, 8]), caller=None)
    expected = walk(ready, patient, page_size=50)
    assert expected[:3] == ["med_patients.a 9", "med_patients.b 8", "med_patients.a 7"]
    assert len(expected) == 9
    for size in (1, 2, 4):
        with subtests.test(page_size=size):
            assert walk(ready, patient, page_size=size) == expected


def test_failing_and_disabled_providers(ready, caplog):
    patient = new_patient(ready, full_name="Nome Que Não Vai Ao Log")
    TIMELINE_PROVIDERS.add("med_patients.ok", make_provider("med_patients.ok", [1]), caller=None)

    def broken(**kwargs):
        raise RuntimeError("boom")

    TIMELINE_PROVIDERS.add("med_patients.broken", broken, caller=None)
    TIMELINE_PROVIDERS.add("med_scheduling.other", make_provider("med_scheduling.other", [2]), caller=None)
    with caplog.at_level(logging.WARNING), ready.app_disabled("med_scheduling"):
        with ready.as_user(ready.a.reception) as actor:
            page = PatientService().timeline(actor=actor, patient_id=patient.sysid)
    assert [item.source for item in page.items] == ["med_patients.ok"]
    assert page.unavailable == ("med_patients.broken",)
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "med_patients.broken" in logged
    assert str(patient.sysid) not in logged and "Nome Que" not in logged


def test_sections_and_setup_steps_follow_active_apps(ready):
    PATIENT_SECTIONS.add("med_patients.x", PatientSection("med_patients.x", "Própria", "a:b", order=50), caller=None)
    PATIENT_SECTIONS.add("med_scheduling.y", PatientSection("med_scheduling.y", "Agenda", "c:d", order=10), caller=None)
    SETUP_STEPS.add("med_patients.s", SetupStep("med_patients.s", "Passo", "a:b", lambda **kw: True), caller=None)

    def explode(**kwargs):
        raise RuntimeError("no")

    SETUP_STEPS.add("med_patients.t", SetupStep("med_patients.t", "Quebrado", "a:b", explode, order=200), caller=None)
    with ready.as_user(ready.a.reception) as actor:
        assert [row.code for row in PatientService().patient_sections(actor=actor)] == [
            "med_scheduling.y",
            "med_patients.x",
        ]
        with pytest.raises(Forbidden):
            PatientService().setup_steps(actor=actor)
    with ready.app_disabled("med_scheduling"), ready.as_user(ready.a.reception) as actor:
        assert [row.code for row in PatientService().patient_sections(actor=actor)] == ["med_patients.x"]
    with ready.as_user(ready.a.admin) as admin:
        steps = PatientService().setup_steps(actor=admin)
    assert [(row.code, row.done) for row in steps] == [("med_patients.s", True), ("med_patients.t", False)]


def test_delete_consults_every_retention_guard(ready):
    patient = new_patient(ready)
    RETENTION_GUARDS.add("med_patients.keep", lambda *, patient_id: "Guarda legal do prontuário.", caller=None)
    RETENTION_GUARDS.add("med_patients.free", lambda *, patient_id: None, caller=None)
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict) as error:
            PatientService().delete(actor=actor, patient_id=patient.sysid, expected_revision=1)
        assert error.value.code == "retention" and "Guarda legal" in str(error.value.detail)

        def broken(*, patient_id):
            raise RuntimeError("down")

        RETENTION_GUARDS.restore({"med_patients.broken": broken})
        with pytest.raises(Conflict):
            PatientService().delete(actor=actor, patient_id=patient.sysid, expected_revision=1)
        RETENTION_GUARDS.restore({})
        PatientService().delete(actor=actor, patient_id=patient.sysid, expected_revision=1)
