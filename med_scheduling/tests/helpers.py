"""Shared preparation of the scheduling tests, through the public services of the suite."""

from __future__ import annotations

from typing import Any

from applications.med_patients.service_api import PatientInput, PatientService

from ..service_api import SchedulingService


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
            idempotency_key="practice",
        )


def new_patient(clinic: Any, side: Any = None, **values: Any) -> Any:
    side = side or clinic.a
    values.setdefault("full_name", "Paciente da Agenda")
    with clinic.as_user(side.reception, side.organization) as actor:
        return PatientService().create(actor=actor, data=PatientInput(**values))


def as_admin(clinic: Any, side: Any = None) -> Any:
    side = side or clinic.a
    return clinic.as_user(side.admin, side.organization)


class Prepared:
    """The clinic fixture plus what a test prepared (``ready.schedule``), forwarding everything else."""

    def __init__(self, clinic: Any, **extra: Any) -> None:
        self._clinic = clinic
        self.__dict__.update(extra)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._clinic, name)
