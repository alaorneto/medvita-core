"""Shared preparation of the records tests, through the public services of the suite."""

from __future__ import annotations

from typing import Any

from applications.med_patients.service_api import PatientInput, PatientService
from applications.med_scheduling.service_api import SchedulingService

from ..service_api import RecordsService

REQUIRED_APPS = ("med_patients", "med_scheduling", "skeleton_calendar")


def setup_patients(clinic: Any, side: Any = None) -> Any:
    side = side or clinic.a
    with clinic.as_user(side.admin, side.organization) as admin:
        return PatientService().setup(
            actor=admin,
            name="Pacientes",
            writer_group_ids=(side.groups["reception"], side.groups["professionals"]),
            reader_group_ids=(side.groups["finance"],),
            idempotency_key="patients",
        )


def setup_practice(clinic: Any, side: Any = None) -> Any:
    side = side or clinic.a
    with clinic.as_user(side.admin, side.organization) as admin:
        return SchedulingService().setup(
            actor=admin,
            practice_name="Consultório Central",
            reader_group_ids=tuple(side.groups.values()),
            manager_group_ids=(side.groups["reception"],),
            idempotency_key="practice",
        )


def register_doctor(clinic: Any, side: Any = None, **values: Any) -> Any:
    side = side or clinic.a
    values.setdefault("display_name", "Dra. Ana")
    values.setdefault("council_number", "123456")
    values.setdefault("council_state", "SP")
    with clinic.as_user(side.admin, side.organization) as admin:
        return SchedulingService().register_professional(
            actor=admin, membership_user_id=side.doctor.pk, idempotency_key=f"doctor-{side.doctor.pk}", **values
        )


def setup_archive(clinic: Any, side: Any = None, *, mode: str = "shared") -> Any:
    """The records of a side: the shared archive written by the professionals group (or per professional)."""
    side = side or clinic.a
    with clinic.as_user(side.admin, side.organization) as admin:
        return RecordsService().setup(
            actor=admin, mode=mode, member_group_ids=(side.groups["professionals"],), idempotency_key="records"
        )


def prepare(clinic: Any, *, mode: str = "shared") -> Any:
    for side in (clinic.a, clinic.b):
        setup_patients(clinic, side)
        setup_practice(clinic, side)
        register_doctor(clinic, side)
        setup_archive(clinic, side, mode=mode)
    return clinic


def new_patient(clinic: Any, side: Any = None, **values: Any) -> Any:
    side = side or clinic.a
    values.setdefault("full_name", "Paciente do Prontuário")
    with clinic.as_user(side.reception, side.organization) as actor:
        return PatientService().create(actor=actor, data=PatientInput(**values))


def open_chart(clinic: Any, patient: Any, side: Any = None, user: Any = None) -> Any:
    side = side or clinic.a
    with clinic.as_user(user or side.doctor, side.organization) as actor:
        return RecordsService().open_chart(actor=actor, patient_id=patient.sysid)
