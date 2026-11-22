"""available_slots against the database: grid, blocks, live appointments and the professional's calendar."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import InvalidInput, NotFound

from ..service_api import AvailabilityRuleInput, SchedulingService
from .booking import book, prepare
from .helpers import Prepared, as_admin, setup_patients, setup_practice

SP = ZoneInfo("America/Sao_Paulo")


def next_monday() -> date:
    today = date.today() + timedelta(days=7)
    return today + timedelta(days=(7 - today.weekday()) % 7)


@pytest.fixture
def ready(clinic):
    setup_patients(clinic)
    setup_practice(clinic)
    with as_admin(clinic) as admin:
        doctor = SchedulingService().register_professional(
            actor=admin, display_name="Dra. Ana", membership_user_id=clinic.a.doctor.pk, idempotency_key="ana"
        )
        schedule = SchedulingService().create_schedule(
            actor=admin,
            name="Agenda",
            professional_id=doctor.sysid,
            writer_group_ids=(clinic.a.groups["reception"],),
            idempotency_key="agenda",
        )
    with clinic.as_user(clinic.a.reception) as actor:
        SchedulingService().set_availability(
            actor=actor,
            schedule_id=schedule.sysid,
            rules=(AvailabilityRuleInput(0, 8 * 60, 10 * 60, date(2026, 1, 1)),),
            expected_revision=schedule.revision,
        )
    return Prepared(clinic, schedule=schedule, monday=next_monday())


def free(ready, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        found = SchedulingService().available_slots(
            actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
        )
    return [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in found]


def at(ready, hour, minute=0):
    day = ready.monday
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SP)


def test_grid_blocks_and_the_professional_calendar(ready):
    assert free(ready) == ["08:00", "08:30", "09:00", "09:30"]
    with ready.as_user(ready.a.reception) as actor:
        SchedulingService().add_block(
            actor=actor, schedule_id=ready.schedule.sysid, starts_at=at(ready, 8, 30), ends_at=at(ready, 9)
        )
    assert free(ready) == ["08:00", "09:00", "09:30"]
    with ready.as_user(ready.a.doctor) as actor:
        personal = next(calendar for calendar in CalendarService().my_calendars(actor=actor) if calendar.is_default)
        CalendarService().create_event(
            actor=actor,
            calendar_id=personal.sysid,
            data={"title": "Compromisso", "starts_at": at(ready, 9, 15), "ends_at": at(ready, 9, 45), "tzid": "UTC"},
        )
    assert free(ready) == ["08:00"]


def test_reading_needs_the_schedule(ready):
    with ready.as_user(ready.a.finance) as actor, pytest.raises(NotFound):
        SchedulingService().available_slots(
            actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
        )
    with ready.as_user(ready.a.reception) as actor, pytest.raises(InvalidInput):
        SchedulingService().available_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            start_date=ready.monday,
            end_date=ready.monday + timedelta(days=62),
        )


FULL = ["08:00", "08:30", "09:00", "09:30"]


def unlinked_schedule(ready, target):
    """A schedule no personal calendar answers for: of a room, or of a professional with no member linked."""
    service = SchedulingService()
    with as_admin(ready) as admin:
        if target == "room":
            owner = {"room_id": service.add_room(actor=admin, name="Sala 1", idempotency_key="sala").sysid}
        else:
            solo = service.register_professional(actor=admin, display_name="Dr. Sem Usuário", idempotency_key="solo")
            owner = {"professional_id": solo.sysid}
        schedule = service.create_schedule(
            actor=admin,
            name=f"Agenda {target}",
            writer_group_ids=(ready.a.groups["reception"],),
            idempotency_key=target,
            **owner,
        )
        service.set_availability(
            actor=admin,
            schedule_id=schedule.sysid,
            rules=(AvailabilityRuleInput(0, 8 * 60, 10 * 60, date(2026, 1, 1)),),
            expected_revision=schedule.revision,
        )
    return schedule


def hours(found):
    return [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in found]


def free_both_ways(ready, schedule):
    """The free slots as ``available_slots`` and as ``day`` see them: they must agree."""
    with ready.as_user(ready.a.reception) as actor:
        listed = SchedulingService().available_slots(
            actor=actor, schedule_id=schedule.sysid, start_date=ready.monday, end_date=ready.monday
        )
        (agenda,) = SchedulingService().day(actor=actor, date=ready.monday, schedule_ids=(schedule.sysid,))
    assert hours(listed) == hours(agenda.free)
    return hours(listed)


def step(ready, name, appointment, **extra):
    with ready.as_user(ready.a.reception) as actor:
        return getattr(SchedulingService(), name)(
            actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision, **extra
        )


def test_live_appointments_leave_the_free_slots_without_a_linked_person(clinic, subtests, monkeypatch):
    ready = prepare(clinic)
    for target in ("room", "professional"):
        with subtests.test(target):
            schedule = unlinked_schedule(ready, target)
            assert free_both_ways(ready, schedule) == FULL
            cancelled = book(ready, 9, key=f"{target}-cancelled", schedule_id=schedule.sysid)
            assert free_both_ways(ready, schedule) == ["08:00", "08:30", "09:30"]
            step(ready, "cancel", cancelled, reason="patient")
            assert free_both_ways(ready, schedule) == FULL
            completed = book(ready, 8, 30, key=f"{target}-completed", schedule_id=schedule.sysid)
            arrived = step(ready, "check_in", step(ready, "confirm", completed))
            assert free_both_ways(ready, schedule) == ["08:00", "09:00", "09:30"]
            step(ready, "complete", arrived)
            assert free_both_ways(ready, schedule) == FULL
            missed = book(ready, 9, 30, key=f"{target}-missed", schedule_id=schedule.sysid)
            assert free_both_ways(ready, schedule) == ["08:00", "08:30", "09:00"]
            with monkeypatch.context() as clock:
                clock.setattr("django.utils.timezone.now", lambda: at(ready, 9, 45))
                assert step(ready, "mark_no_show", missed).status == "no_show"
            assert free_both_ways(ready, schedule) == FULL


def test_the_type_of_the_window_still_filters_the_slots(clinic):
    ready = prepare(clinic)
    service = SchedulingService()
    with as_admin(ready) as admin:
        follow_up = service.add_appointment_type(
            actor=admin, code="retorno", name="Retorno", duration_minutes=30, idempotency_key="retorno"
        )
        current = service.schedule(actor=admin, schedule_id=ready.schedule.sysid)
        service.set_availability(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            rules=(
                AvailabilityRuleInput(0, 8 * 60, 9 * 60, date(2026, 1, 1)),
                AvailabilityRuleInput(0, 9 * 60, 10 * 60, date(2026, 1, 1), appointment_type_id=follow_up.sysid),
            ),
            expected_revision=current.revision,
        )

    def listed(kind=None):
        with ready.as_user(ready.a.reception) as actor:
            found = service.available_slots(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                start_date=ready.monday,
                end_date=ready.monday,
                appointment_type_id=kind,
            )
        return hours(found)

    assert listed(follow_up.sysid) == FULL
    assert listed(ready.kind.sysid) == listed() == ["08:00", "08:30"]
