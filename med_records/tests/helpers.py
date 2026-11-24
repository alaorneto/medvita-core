"""Shared preparation of the records tests, through the public services of the suite."""

from __future__ import annotations

from typing import Any

from applications.med_patients.service_api import PatientInput, PatientService
from applications.med_scheduling.service_api import SchedulingService

from ..service_api import RecordsService

REQUIRED_APPS = ("med_patients", "med_scheduling")


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


def monday_at(hour: int, minute: int = 0) -> Any:
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    day = date.today() + timedelta(days=7)
    day += timedelta(days=(7 - day.weekday()) % 7)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo("America/Sao_Paulo"))


def book_arrived(clinic: Any, patient: Any, professional: Any, side: Any = None) -> Any:
    """A Monday 09:00 appointment of the patient with the professional, checked in by the reception."""
    from datetime import date

    from applications.med_scheduling.service_api import AvailabilityRuleInput

    side = side or clinic.a
    scheduling = SchedulingService()
    with clinic.as_user(side.admin, side.organization) as admin:
        kind = scheduling.add_appointment_type(
            actor=admin, code="consulta", name="Consulta", duration_minutes=30, idempotency_key="kind"
        )
        schedule = scheduling.create_schedule(
            actor=admin,
            name="Agenda",
            professional_id=professional.sysid,
            writer_group_ids=(side.groups["reception"],),
            writer_user_ids=(side.doctor.pk,),
            idempotency_key="schedule",
        )
    with clinic.as_user(side.reception, side.organization) as actor:
        scheduling.set_availability(
            actor=actor,
            schedule_id=schedule.sysid,
            rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),),
            expected_revision=schedule.revision,
        )
        booked = scheduling.book(
            actor=actor,
            schedule_id=schedule.sysid,
            patient_id=patient.sysid,
            appointment_type_id=kind.sysid,
            starts_at=monday_at(9),
            idempotency_key=f"book-{patient.sysid}",
        )
        return scheduling.check_in(actor=actor, appointment_id=booked.sysid, expected_revision=booked.revision)


def start(clinic: Any, chart: Any, *, key: str = "draft", user: Any = None, side: Any = None, **values: Any) -> Any:
    side = side or clinic.a
    with clinic.as_user(user or side.doctor, side.organization) as actor:
        return RecordsService().start_encounter(actor=actor, chart_id=chart.sysid, idempotency_key=key, **values)


def save(clinic: Any, encounter: Any, section_type: str, data=(), text: str = "", *, user: Any = None, **values: Any):
    with clinic.as_user(user or clinic.a.doctor) as actor:
        return RecordsService().save_section(
            actor=actor,
            encounter_id=encounter.header.sysid,
            section_type=section_type,
            data=tuple(data),
            text=text,
            expected_revision=values.pop("expected_revision", encounter.header.revision),
            **values,
        )
