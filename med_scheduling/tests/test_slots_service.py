"""available_slots against the database: grid, blocks and the professional's own calendar."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import InvalidInput, NotFound

from ..service_api import AvailabilityRuleInput, SchedulingService
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
