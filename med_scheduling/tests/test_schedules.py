"""Schedules with their shared calendar, mirrored access, weekly grid and blocks."""

from datetime import UTC, date, datetime, timedelta
from itertools import count

import pytest

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, Unavailable
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import acting_as, build_service_scenario

from ..models import AvailabilityRule, Practice, Room, Schedule, ScheduleBlock
from ..service_api import AvailabilityRuleInput, SchedulingService
from .helpers import Prepared, as_admin, setup_patients, setup_practice


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    setup_patients(clinic)
    setup_practice(clinic)
    with as_admin(clinic) as admin:
        doctor = service().register_professional(
            actor=admin, display_name="Dra. Ana", membership_user_id=clinic.a.doctor.pk, idempotency_key="ana"
        )
        schedule = service().create_schedule(
            actor=admin,
            name="Agenda da Dra. Ana",
            professional_id=doctor.sysid,
            writer_group_ids=(clinic.a.groups["reception"],),
            reader_group_ids=(clinic.a.groups["professionals"],),
            idempotency_key="ana",
        )
    return Prepared(clinic, schedule=schedule, doctor=doctor)


def calendar_ids(clinic, user):
    with clinic.as_user(user) as actor:
        return {calendar.sysid for calendar in CalendarService().calendars(actor=actor)}


def test_create_schedule_with_its_calendar_and_access(ready, subtests):
    schedule = ready.schedule
    with subtests.test("idempotent"), as_admin(ready) as admin:
        again = service().create_schedule(
            actor=admin, name="Outro nome", professional_id=ready.doctor.sysid, idempotency_key="ana"
        )
        assert again.sysid == schedule.sysid
    with subtests.test("reception writes"), ready.as_user(ready.a.reception) as actor:
        assert service().schedule(actor=actor, schedule_id=schedule.sysid).writable
    assert schedule.calendar_id in calendar_ids(ready, ready.a.reception)
    with subtests.test("the professional owns it"), ready.as_user(ready.a.doctor) as actor:
        assert service().schedule(actor=actor, schedule_id=schedule.sysid).writable
    with subtests.test("finance sees nothing"), ready.as_user(ready.a.finance) as actor:
        assert service().schedules(actor=actor) == ()
        with pytest.raises(NotFound):
            service().schedule(actor=actor, schedule_id=schedule.sysid)
    with subtests.test("only the access manager creates"), ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Forbidden):
            service().create_schedule(actor=actor, name="X", professional_id=ready.doctor.sysid, idempotency_key="x")
    with subtests.test("needs a professional or a room"), as_admin(ready) as admin:
        with pytest.raises(InvalidInput):
            service().create_schedule(actor=admin, name="Vazia", idempotency_key="empty")


def test_set_schedule_access_mirrors_the_calendar(ready):
    schedule = ready.schedule
    with as_admin(ready) as admin:
        service().set_schedule_access(
            actor=admin,
            schedule_id=schedule.sysid,
            writer_group_ids=(ready.a.groups["finance"],),
            reader_group_ids=(),
            expected_revision=schedule.revision,
        )
    with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
        service().schedule(actor=actor, schedule_id=schedule.sysid)
    assert schedule.calendar_id not in calendar_ids(ready, ready.a.reception)
    with ready.as_user(ready.a.finance) as actor:
        assert service().schedule(actor=actor, schedule_id=schedule.sysid).writable
    assert schedule.calendar_id in calendar_ids(ready, ready.a.finance)


def test_weekly_grid_replaces_with_cas(ready, subtests):
    schedule = ready.schedule
    with ready.as_user(ready.a.reception) as actor:
        current = service().schedule(actor=actor, schedule_id=schedule.sysid)
        morning = AvailabilityRuleInput(weekday=0, start_minute=8 * 60, end_minute=12 * 60, valid_from=date(2026, 1, 1))
        afternoon = AvailabilityRuleInput(
            weekday=0, start_minute=14 * 60, end_minute=18 * 60, valid_from=date(2026, 1, 1)
        )
        rules = service().set_availability(
            actor=actor, schedule_id=schedule.sysid, rules=(afternoon, morning), expected_revision=current.revision
        )
        assert [rule.start_minute for rule in rules] == [480, 840]
        with pytest.raises(Conflict):
            service().set_availability(
                actor=actor, schedule_id=schedule.sysid, rules=(morning,), expected_revision=current.revision
            )
        fresh = service().schedule(actor=actor, schedule_id=schedule.sysid).revision
        for name, bad in (
            ("overlap", (morning, AvailabilityRuleInput(0, 11 * 60, 13 * 60, date(2026, 1, 1)))),
            ("inverted", (AvailabilityRuleInput(1, 600, 540, date(2026, 1, 1)),)),
            ("weekday", (AvailabilityRuleInput(7, 60, 120, date(2026, 1, 1)),)),
        ):
            with subtests.test(name), pytest.raises(InvalidInput):
                service().set_availability(actor=actor, schedule_id=schedule.sysid, rules=bad, expected_revision=fresh)
        replaced = service().set_availability(
            actor=actor, schedule_id=schedule.sysid, rules=(morning,), expected_revision=fresh
        )
        assert len(replaced) == 1 and len(service().availability(actor=actor, schedule_id=schedule.sysid)) == 1


def test_blocks_show_in_the_calendar(ready):
    schedule = ready.schedule
    start = datetime(2026, 12, 24, 13, 0, tzinfo=UTC)
    with ready.as_user(ready.a.reception) as actor:
        block = service().add_block(
            actor=actor,
            schedule_id=schedule.sysid,
            starts_at=start,
            ends_at=start + timedelta(hours=4),
            reason="holiday",
        )
        busy = CalendarService().calendar_busy(
            actor=actor,
            calendar_ids=(schedule.calendar_id,),
            start=start - timedelta(days=1),
            end=start + timedelta(days=1),
        )
        assert [(item.starts_at, item.ends_at) for item in busy] == [(start, start + timedelta(hours=4))]
        with pytest.raises(InvalidInput):
            service().add_block(actor=actor, schedule_id=schedule.sysid, starts_at=start, ends_at=start)
        service().remove_block(actor=actor, block_id=block.sysid, expected_revision=block.revision)
        busy = CalendarService().calendar_busy(
            actor=actor,
            calendar_ids=(schedule.calendar_id,),
            start=start - timedelta(days=1),
            end=start + timedelta(days=1),
        )
        assert busy == ()


def test_calendar_disabled_makes_scheduling_unavailable(ready):
    with ready.app_disabled("skeleton_calendar"), as_admin(ready) as admin:
        with pytest.raises(Unavailable):
            service().create_schedule(actor=admin, name="X", professional_id=ready.doctor.sysid, idempotency_key="off")


@pytest.mark.parametrize("model", [AvailabilityRule, ScheduleBlock])
def test_grid_and_blocks_follow_the_schedule(skeleton_db, model):
    for label in ("med_patients", "skeleton_calendar", "med_scheduling"):
        open_app(label)
    scenario = build_service_scenario(model, slug=f"schedule-{model._meta.model_name}")
    calendars = {}
    for organization, admin in ((scenario.a, scenario.admin_a), (scenario.b, scenario.admin_b)):
        with acting_as(admin, organization) as actor:
            calendars[organization.pk] = (
                CalendarService()
                .create_shared_calendar(
                    actor=actor, name="Base", owner_user_id=admin.pk, timezone="UTC", idempotency_key="base"
                )
                .sysid
            )
    numbers = count(1)

    def make_schedule(*, organization, owner):
        practice = Practice(organization=organization, owner=owner, visibility="private", name=f"C{next(numbers)}")
        practice.save()
        room = Room(organization=organization, practice=practice, name="Sala")
        room.save()
        schedule = Schedule(
            organization=organization,
            owner=owner,
            visibility="private",
            practice=practice,
            name="Agenda",
            room=room,
            calendar_id=calendars[organization.pk],
        )
        schedule.save()
        return schedule

    def make_row(schedule):
        if model is AvailabilityRule:
            row = AvailabilityRule(
                organization=schedule.organization,
                schedule=schedule,
                weekday=1,
                start_minute=480,
                end_minute=600,
                valid_from=date(2026, 1, 1),
            )
        else:
            start = datetime(2026, 5, 5, 12, tzinfo=UTC)
            row = ScheduleBlock(
                organization=schedule.organization,
                schedule=schedule,
                starts_at=start,
                ends_at=start + timedelta(hours=1),
            )
        row.save()
        return row

    assert_derived_access_contract(child_model=model, make_anchor=make_schedule, make_child=make_row, scenario=scenario)
