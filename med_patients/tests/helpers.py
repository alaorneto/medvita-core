"""Shared preparation of the patients tests: the default registry and patients through the public service."""

from __future__ import annotations

from typing import Any

from ..service_api import PatientInput, PatientService


def setup_registry(clinic: Any, side: Any = None, *, key: str = "setup") -> Any:
    """The default registry of ``side`` (A by default): reception and doctors write, finance reads."""
    side = side or clinic.a
    with clinic.as_user(side.admin, side.organization) as admin:
        return PatientService().setup(
            actor=admin,
            name="Pacientes da clínica",
            writer_group_ids=(side.groups["reception"], side.groups["professionals"]),
            reader_group_ids=(side.groups["finance"],),
            idempotency_key=key,
        )


def new_patient(clinic: Any, side: Any = None, *, user: Any = None, **values: Any) -> Any:
    """Register a patient as the receptionist of ``side`` (A by default) and return its PatientInfo."""
    side = side or clinic.a
    values.setdefault("full_name", "Maria da Silva")
    with clinic.as_user(user or side.reception, side.organization) as actor:
        return PatientService().create(actor=actor, data=PatientInput(**values))
