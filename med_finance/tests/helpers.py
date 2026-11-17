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


def book(
    clinic: Any, patient: Any, *, payment_kind: str = "private", billing_code: str = "C1", side: Any = None
) -> Any:
    """A Monday 09:00 appointment of the patient with the doctor, checked in by the reception."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from applications.med_scheduling.service_api import AvailabilityRuleInput

    side = side or clinic.a
    scheduling = SchedulingService()
    with clinic.as_user(side.admin, side.organization) as admin:
        doctor = scheduling.register_professional(
            actor=admin,
            display_name="Dra. Ana",
            council_number="123456",
            council_state="SP",
            tax_id="52998224725",
            membership_user_id=side.doctor.pk,
            idempotency_key="doctor",
        )
        kind = scheduling.add_appointment_type(
            actor=admin, code="consulta", name="Consulta", billing_code=billing_code, idempotency_key="kind"
        )
        schedule = scheduling.create_schedule(
            actor=admin,
            name="Agenda",
            professional_id=doctor.sysid,
            writer_group_ids=(side.groups["reception"],),
            idempotency_key="schedule",
        )
    day = date.today() + timedelta(days=7)
    day += timedelta(days=(7 - day.weekday()) % 7)
    with clinic.as_user(side.reception, side.organization) as actor:
        current = scheduling.schedule(actor=actor, schedule_id=schedule.sysid)
        if not scheduling.availability(actor=actor, schedule_id=schedule.sysid):
            scheduling.set_availability(
                actor=actor,
                schedule_id=schedule.sysid,
                rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),),
                expected_revision=current.revision,
            )
        booked = scheduling.book(
            actor=actor,
            schedule_id=schedule.sysid,
            patient_id=patient.sysid,
            appointment_type_id=kind.sysid,
            starts_at=datetime(day.year, day.month, day.day, 9, tzinfo=ZoneInfo("America/Sao_Paulo")),
            fit_in=True,
            payment_kind=payment_kind,
            idempotency_key=f"book-{patient.sysid}",
        )
        return scheduling.check_in(actor=actor, appointment_id=booked.sysid, expected_revision=booked.revision)
