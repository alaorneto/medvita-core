"""A clinic set up through the public services of the four apps, for the cross-app tests of the suite.

Organization A and B each get: the patient registry, the practice with Dra. Ana (the doctor of the
clinic fixture) and her schedule (Mondays 08:00–12:00, written by the reception), the shared
clinical archive (professionals), the cash desk (reception and finance) and the price C1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from applications.med_finance.service_api import FinanceService
from applications.med_patients.service_api import PatientInput, PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import AvailabilityRuleInput, SchedulingService

SP = ZoneInfo("America/Sao_Paulo")


@dataclass
class Clinic:
    side: Any
    professional: Any
    kind: Any
    schedule: Any


def next_monday() -> date:
    day = date.today() + timedelta(days=7)
    return day + timedelta(days=(7 - day.weekday()) % 7)


def monday_at(hour: int, minute: int = 0) -> datetime:
    day = next_monday()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SP)


def set_up(clinic: Any, side: Any) -> Clinic:
    groups = side.groups
    with clinic.as_user(side.admin, side.organization) as admin:
        PatientService().setup(
            actor=admin,
            name="Pacientes",
            writer_group_ids=(groups["reception"], groups["professionals"]),
            reader_group_ids=(groups["finance"],),
            idempotency_key="patients",
        )
        scheduling = SchedulingService()
        scheduling.setup(
            actor=admin,
            practice_name="Consultório Central",
            reader_group_ids=tuple(groups.values()),
            manager_group_ids=(groups["reception"],),
            idempotency_key="practice",
        )
        professional = scheduling.register_professional(
            actor=admin,
            display_name="Dra. Ana",
            council_number="123456",
            council_state="SP",
            tax_id="52998224725",
            membership_user_id=side.doctor.pk,
            idempotency_key="doctor",
        )
        kind = scheduling.add_appointment_type(
            actor=admin, code="consulta", name="Consulta", billing_code="C1", idempotency_key="kind"
        )
        schedule = scheduling.create_schedule(
            actor=admin,
            name="Agenda da Dra. Ana",
            professional_id=professional.sysid,
            writer_group_ids=(groups["reception"],),
            writer_user_ids=(side.doctor.pk,),
            idempotency_key="schedule",
        )
        RecordsService().setup(actor=admin, member_group_ids=(groups["professionals"],), idempotency_key="records")
        FinanceService().setup(
            actor=admin,
            writer_group_ids=(groups["reception"], groups["finance"]),
            price_manager_group_ids=(groups["finance"],),
            idempotency_key="finance",
        )
    with clinic.as_user(side.reception, side.organization) as actor:
        scheduling.set_availability(
            actor=actor,
            schedule_id=schedule.sysid,
            rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),),
            expected_revision=schedule.revision,
        )
    with clinic.as_user(side.finance, side.organization) as actor:
        FinanceService().add_price_item(
            actor=actor, code="C1", description="Consulta", amount=25000, idempotency_key="price"
        )
    return Clinic(side, professional, kind, schedule)


def new_patient(clinic: Any, side: Any, **values: Any) -> Any:
    with clinic.as_user(side.reception, side.organization) as actor:
        return PatientService().create(actor=actor, data=PatientInput(**values))
