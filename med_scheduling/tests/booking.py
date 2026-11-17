"""A ready clinic for the appointment tests: patients, practice, a professional's schedule and a grid."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..service_api import AvailabilityRuleInput, SchedulingService
from .helpers import Prepared, as_admin, new_patient, setup_patients, setup_practice

SP = ZoneInfo("America/Sao_Paulo")


def next_monday() -> date:
    day = date.today() + timedelta(days=7)
    return day + timedelta(days=(7 - day.weekday()) % 7)


def prepare(clinic: Any) -> Prepared:
    """Practice, Dra. Ana's schedule (reception writes, 08:00-12:00 on Mondays), a type and a patient."""
    for side in (clinic.a, clinic.b):
        setup_patients(clinic, side)
        setup_practice(clinic, side)
    service = SchedulingService()
    with as_admin(clinic) as admin:
        doctor = service.register_professional(
            actor=admin, display_name="Dra. Ana", membership_user_id=clinic.a.doctor.pk, idempotency_key="ana"
        )
        kind = service.add_appointment_type(
            actor=admin, code="consulta", name="Consulta", duration_minutes=30, billing_code="C1", idempotency_key="t"
        )
        schedule = service.create_schedule(
            actor=admin,
            name="Agenda da Dra. Ana",
            professional_id=doctor.sysid,
            writer_group_ids=(clinic.a.groups["reception"],),
            idempotency_key="ana",
        )
    with clinic.as_user(clinic.a.reception) as actor:
        service.set_availability(
            actor=actor,
            schedule_id=schedule.sysid,
            rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),),
            expected_revision=schedule.revision,
        )
    patient = new_patient(clinic, full_name="Maria Paciente Secreta")
    return Prepared(clinic, doctor=doctor, kind=kind, schedule=schedule, patient=patient, monday=next_monday())


def at(ready: Any, hour: int, minute: int = 0, *, day: date | None = None) -> datetime:
    day = day or ready.monday
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SP)


def book(ready: Any, hour: int, minute: int = 0, *, key: str | None = None, user: Any = None, **extra: Any) -> Any:
    with ready.as_user(user or ready.a.reception) as actor:
        return SchedulingService().book(
            actor=actor,
            schedule_id=extra.pop("schedule_id", ready.schedule.sysid),
            patient_id=extra.pop("patient_id", ready.patient.sysid),
            appointment_type_id=ready.kind.sysid,
            starts_at=at(ready, hour, minute),
            idempotency_key=key or f"book-{hour}-{minute}",
            **extra,
        )
