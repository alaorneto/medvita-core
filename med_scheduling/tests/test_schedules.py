"""Schedules with their shared calendar, mirrored access, weekly grid and blocks."""

from datetime import UTC, date, datetime, timedelta
from itertools import count

import pytest

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, Unavailable
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import acting_as, build_service_scenario

from .. import calendar_bridge
from ..models import (
    AppointmentType,
    AvailabilityRule,
    AvailabilityRuleType,
    Practice,
    Room,
    Schedule,
    ScheduleAppointmentType,
    ScheduleBlock,
)
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


def test_calendars_lists_those_of_the_schedules_and_then_the_others(ready, subtests):
    def listed(user, organization=None):
        with ready.as_user(user, organization) as actor:
            return service().calendars(actor=actor)

    with subtests.test("the calendar of the schedule, and nothing is created"):
        (entry,) = listed(ready.a.reception)
        assert (entry.calendar_id, entry.schedule_id) == (ready.schedule.calendar_id, ready.schedule.sysid)
        assert entry.name == "Agenda da Dra. Ana" and entry.schedule_is_active and not entry.is_own
        assert len(listed(ready.a.reception)) == 1
    with ready.as_user(ready.a.reception) as actor:
        personal = CalendarService().my_calendars(actor=actor)[0]
    with subtests.test("then the others, the person's own marked"):
        first, other = listed(ready.a.reception)
        assert first.schedule_id == ready.schedule.sysid
        assert (other.calendar_id, other.kind, other.is_own, other.schedule_id) == (
            personal.sysid,
            "personal",
            True,
            None,
        )
    with subtests.test("the schedules come by name"), as_admin(ready) as admin:
        room = service().add_room(actor=admin, name="Sala 1", idempotency_key="room")
        service().create_schedule(
            actor=admin,
            name="A sala",
            room_id=room.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            idempotency_key="room",
        )
    with subtests.test("by name"):
        names = [entry.name for entry in listed(ready.a.reception) if entry.schedule_id]
        assert names == ["A sala", "Agenda da Dra. Ana"]
    with subtests.test("who reads no schedule sees none, and nobody sees another person's personal calendar"):
        assert listed(ready.a.finance) == ()
    with subtests.test("organization B sees nothing of A"):
        assert listed(ready.b.admin, ready.b.organization) == ()


def origin(clinic, user, calendar_id):
    """The app the core has the calendar as managed by, and the page it points at."""
    with clinic.as_user(user) as actor:
        (info,) = [item for item in CalendarService().calendars(actor=actor) if item.sysid == calendar_id]
    return info.source_app, info.source_path


def unmarked_calendar(actor, *, schedule_id, idempotency_key, **values):
    """The calendar of a schedule as it was created before the core had the marker: with no origin."""
    return (
        CalendarService().create_shared_calendar(actor=actor, idempotency_key=f"old:{idempotency_key}", **values).sysid
    )


def test_the_calendar_of_a_schedule_is_managed_by_the_app(ready, subtests, monkeypatch):
    schedule = ready.schedule
    reception = ready.a.groups["reception"]
    with subtests.test("a new schedule is born managed, pointing at its page"):
        assert origin(ready, ready.a.reception, schedule.calendar_id) == (
            "med_scheduling",
            f"apps/med_scheduling/schedules/{schedule.sysid}/",
        )
        with ready.as_user(ready.a.reception) as actor:
            (entry,) = service().calendars(actor=actor)
        assert entry.is_managed and entry.writable
    with subtests.test("with nothing to mark, the step marks nothing"), as_admin(ready) as admin:
        assert service().claim_schedule_calendars(actor=admin) == 0
    # A schedule of before the marker, of another professional: the calendar belongs to that person.
    with as_admin(ready) as admin, monkeypatch.context() as patched:
        patched.setattr(calendar_bridge, "create_calendar", unmarked_calendar)
        other = service().register_professional(
            actor=admin, display_name="Dr. Caio", membership_user_id=ready.a.finance.pk, idempotency_key="caio"
        )
        old = service().create_schedule(
            actor=admin,
            name="Agenda do Dr. Caio",
            professional_id=other.sysid,
            writer_group_ids=(reception,),
            idempotency_key="caio",
        )
    assert origin(ready, ready.a.reception, old.calendar_id) == ("", "")
    with subtests.test("the list says which calendar is not managed yet"), ready.as_user(ready.a.reception) as actor:
        flags = {entry.schedule_id: entry.is_managed for entry in service().calendars(actor=actor)}
        assert flags == {schedule.sysid: True, old.sysid: False}
    with subtests.test("only who manages access marks"):
        with ready.as_user(ready.a.reception) as actor, pytest.raises(Forbidden):
            service().claim_schedule_calendars(actor=actor)
        assert origin(ready, ready.a.reception, old.calendar_id) == ("", "")
    with subtests.test("organization B marks nothing of A"):
        with ready.as_user(ready.b.admin, ready.b.organization) as actor:
            assert service().claim_schedule_calendars(actor=actor) == 0
        assert origin(ready, ready.a.reception, old.calendar_id) == ("", "")
    with subtests.test("the old schedule is marked once; repeating marks nothing"), as_admin(ready) as admin:
        assert service().claim_schedule_calendars(actor=admin) == 1
        assert service().claim_schedule_calendars(actor=admin) == 0
    assert origin(ready, ready.a.reception, old.calendar_id) == (
        "med_scheduling",
        f"apps/med_scheduling/schedules/{old.sysid}/",
    )
    with subtests.test("the access of a managed calendar still follows the schedule"):
        with as_admin(ready) as admin:
            service().set_schedule_access(
                actor=admin,
                schedule_id=old.sysid,
                writer_group_ids=(),
                reader_group_ids=(ready.a.groups["professionals"],),
                expected_revision=old.revision,
            )
        assert old.calendar_id not in calendar_ids(ready, ready.a.reception)
        assert old.calendar_id in calendar_ids(ready, ready.a.doctor)
        # The owner keeps the calendar: Dr. Caio is the person of the finance team.
        assert old.calendar_id in calendar_ids(ready, ready.a.finance)


def test_calendar_pages_point_at_the_core_for_who_reads_the_calendar(ready, subtests):
    calendar = ready.schedule.calendar_id
    with subtests.test("the page of the calendar and the one of its subscription link"):
        with ready.as_user(ready.a.reception) as actor:
            pages = service().calendar_pages(actor=actor, calendar_id=calendar)
        assert pages.calendar_path == f"apps/skeleton_calendar/calendars/{calendar}/"
        assert pages.subscription_path == f"apps/skeleton_calendar/calendars/{calendar}/link/"
    with subtests.test("who does not read the schedule"):
        with ready.as_user(ready.a.finance) as actor, pytest.raises(NotFound):
            service().calendar_pages(actor=actor, calendar_id=calendar)
    with subtests.test("organization B"):
        with ready.as_user(ready.b.admin, ready.b.organization) as actor, pytest.raises(NotFound):
            service().calendar_pages(actor=actor, calendar_id=calendar)
    with subtests.test("who loses the schedule loses the page, on the next request"):
        with as_admin(ready) as admin:
            service().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(),
                reader_group_ids=(),
                expected_revision=ready.schedule.revision,
            )
        with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
            service().calendar_pages(actor=actor, calendar_id=calendar)


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


def test_the_grid_takes_the_mode_and_the_capacity_of_each_period(ready, subtests):
    start = date(2026, 1, 1)

    def save(*rules, user=None):
        with ready.as_user(user or ready.a.reception) as actor:
            revision = service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
            return service().set_availability(
                actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=revision
            )

    def walk_in(capacity=None, start_minute=480, end_minute=720):
        return AvailabilityRuleInput(0, start_minute, end_minute, start, mode="walk_in", capacity=capacity)

    afternoon = AvailabilityRuleInput(0, 840, 1080, start)
    with subtests.test("a period says its mode; one built as before is of booked time"):
        morning, later = save(walk_in(15), afternoon)
        assert (morning.mode, morning.capacity) == ("walk_in", 15)
        assert (later.mode, later.capacity) == ("booked", None)
        assert save(walk_in(), afternoon)[0].capacity is None
    with subtests.test("mode and capacity change in the row the period already has"):
        rows = AvailabilityRule.all_objects.filter(schedule_id=ready.schedule.sysid)
        with as_admin(ready):
            before = rows.count()
        changed = save(walk_in(20), afternoon)
        booked = save(AvailabilityRuleInput(0, 480, 720, start), afternoon)
        assert changed[0].sysid == booked[0].sysid == morning.sysid
        assert (changed[0].capacity, booked[0].mode, booked[0].capacity) == (20, "booked", None)
        with as_admin(ready):
            assert rows.count() == before
    with subtests.test("periods of different modes do not overlap either"):
        with pytest.raises(InvalidInput) as error:
            save(walk_in(), AvailabilityRuleInput(0, 660, 900, start))
        assert "rules" in error.value.errors
    with subtests.test("a capacity is of a walk-in period, from 1 to 500"):
        for rule in (
            AvailabilityRuleInput(0, 480, 720, start, capacity=10),
            walk_in(0),
            walk_in(501),
            walk_in(True),
            walk_in("10"),
        ):
            with pytest.raises(InvalidInput) as error:
                save(rule)
            assert "capacity" in error.value.errors
        assert save(walk_in(1))[0].capacity == 1 and save(walk_in(500))[0].capacity == 500
    with subtests.test("an unknown mode"):
        for mode in ("queue", "", None, 1):
            with pytest.raises(InvalidInput) as error:
                save(AvailabilityRuleInput(0, 480, 720, start, mode=mode))
            assert "mode" in error.value.errors
    with subtests.test("the database holds the same rules"):
        from django.db import IntegrityError, transaction
        from django.db.models import F, QuerySet

        with as_admin(ready):
            row = QuerySet(AvailabilityRule).filter(schedule_id=ready.schedule.sysid)
            for values in ({"mode": "booked", "capacity": 3}, {"capacity": 0}, {"mode": "queue"}):
                with pytest.raises(IntegrityError, match="med_scheduling_rule_"), transaction.atomic():
                    row.update(revision=F("revision") + 1, **values)


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


@pytest.mark.parametrize("model", [AvailabilityRule, AvailabilityRuleType, ScheduleBlock, ScheduleAppointmentType])
def test_grid_blocks_and_kinds_follow_the_schedule(skeleton_db, model):
    """Every table under a schedule is read and written as the schedule is; the kinds of a period, two hops away."""
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

    def make_kind(schedule):
        kind = AppointmentType(
            organization=schedule.organization, practice=schedule.practice, code=f"t{next(numbers)}", name="Tipo"
        )
        kind.save()
        return kind

    def make_row(schedule):
        if model in (AvailabilityRule, AvailabilityRuleType):
            row = AvailabilityRule(
                organization=schedule.organization,
                schedule=schedule,
                weekday=1,
                start_minute=480,
                end_minute=600,
                valid_from=date(2026, 1, 1),
            )
            if model is AvailabilityRuleType:
                row.save()
                row = AvailabilityRuleType(
                    organization=schedule.organization, rule=row, appointment_type=make_kind(schedule)
                )
        elif model is ScheduleAppointmentType:
            row = ScheduleAppointmentType(
                organization=schedule.organization,
                schedule=schedule,
                appointment_type=make_kind(schedule),
                duration_minutes=40,
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


def test_the_kinds_of_a_period_are_hidden_when_the_period_is_erased(skeleton_db):
    """The way from a kind of a period to the schedule goes through a live period (the middle link)."""
    from skeleton.access.derivation import is_derived
    from skeleton.access.policies import authorized_queryset

    assert is_derived(AvailabilityRuleType) and is_derived(AvailabilityRule)
    for label in ("med_patients", "skeleton_calendar", "med_scheduling"):
        open_app(label)
    scenario = build_service_scenario(AvailabilityRuleType, slug="period-kinds")
    with acting_as(scenario.admin_a, scenario.a) as admin:
        calendar = CalendarService().create_shared_calendar(
            actor=admin, name="Base", owner_user_id=scenario.admin_a.pk, timezone="UTC", idempotency_key="base"
        )
        practice = Practice(organization=scenario.a, owner=scenario.admin_a, visibility="private", name="C")
        practice.save()
        room = Room(organization=scenario.a, practice=practice, name="Sala")
        room.save()
        schedule = Schedule(
            organization=scenario.a,
            owner=scenario.member,
            visibility="private",
            practice=practice,
            name="Agenda",
            room=room,
            calendar_id=calendar.sysid,
        )
        schedule.save()
        kind = AppointmentType(organization=scenario.a, practice=practice, code="t", name="Tipo")
        kind.save()
        rule = AvailabilityRule(
            organization=scenario.a,
            schedule=schedule,
            weekday=1,
            start_minute=480,
            end_minute=600,
            valid_from=date(2026, 1, 1),
        )
        rule.save()
        link = AvailabilityRuleType(organization=scenario.a, rule=rule, appointment_type=kind)
        link.save()

    def visible():
        with acting_as(scenario.member, scenario.a):
            rows = authorized_queryset(AvailabilityRuleType, user=scenario.member, action="read")
            return rows.filter(pk=link.pk).exists()

    assert visible()
    with acting_as(scenario.admin_a, scenario.a):
        rule.delete()
    assert not visible()
