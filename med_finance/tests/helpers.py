"""Shared preparation of the finance tests, through the public services of the suite."""

from __future__ import annotations

from typing import Any

from applications.med_patients.service_api import PatientInput, PatientService
from applications.med_scheduling.service_api import SchedulingService

from ..service_api import FinanceService


def setup_patients(clinic: Any, side: Any) -> Any:
    with clinic.as_user(side.admin, side.organization) as admin:
        return PatientService().setup(
            actor=admin,
            name="Pacientes",
            writer_group_ids=(side.groups["reception"], side.groups["professionals"]),
            reader_group_ids=(side.groups["finance"],),
            idempotency_key="patients",
        )


def setup_practice(clinic: Any, side: Any) -> Any:
    with clinic.as_user(side.admin, side.organization) as admin:
        return SchedulingService().setup(
            actor=admin,
            practice_name="Consultório Central",
            reader_group_ids=tuple(side.groups.values()),
            manager_group_ids=(side.groups["reception"],),
            idempotency_key="practice",
        )


def setup_finance(clinic: Any, side: Any) -> Any:
    """The desk written by reception and finance; prices managed by finance."""
    with clinic.as_user(side.admin, side.organization) as admin:
        return FinanceService().setup(
            actor=admin,
            writer_group_ids=(side.groups["reception"], side.groups["finance"]),
            price_manager_group_ids=(side.groups["finance"],),
            idempotency_key="finance",
        )


def prepare(clinic: Any) -> Any:
    for side in (clinic.a, clinic.b):
        setup_patients(clinic, side)
        setup_practice(clinic, side)
        setup_finance(clinic, side)
    return clinic


def new_patient(clinic: Any, side: Any = None, **values: Any) -> Any:
    side = side or clinic.a
    values.setdefault("full_name", "Paciente do Financeiro")
    with clinic.as_user(side.reception, side.organization) as actor:
        return PatientService().create(actor=actor, data=PatientInput(**values))


def add_price(clinic: Any, code: str = "C1", amount: int = 25000, side: Any = None) -> Any:
    side = side or clinic.a
    with clinic.as_user(side.finance, side.organization) as actor:
        return FinanceService().add_price_item(
            actor=actor, code=code, description=f"Consulta {code}", amount=amount, idempotency_key=f"price-{code}"
        )
