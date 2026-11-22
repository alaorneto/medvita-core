"""Walk-in periods: booking without a time, the room of a session, the queue, the priority mark and the calendar."""

from dataclasses import fields
from datetime import date, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F, QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, InvalidInput, NotFound
from skeleton.service_api.audit import AuditService
from skeleton.service_api.notifications import NotificationService
from skeleton.testing.events import capture_events
from skeleton.testing.jobs import run_pending_jobs
from skeleton.testing.service_api import assert_cas_conflict

from ..models import Appointment
from ..service_api import AppointmentInfo, AvailabilityRuleInput, ScheduleTypeInput, SchedulingService
from .booking import SP, at, book, prepare
from .helpers import as_admin, new_patient

START = date(2026, 1, 1)
AFTERNOON = AvailabilityRuleInput(0, 14 * 60, 18 * 60, START)


def service():
    return SchedulingService()


def walk_in(start=8, end=12, *, capacity=None, kinds=(), weekday=0):
    return AvailabilityRuleInput(
        weekday, start * 60, end * 60, START, appointment_type_ids=kinds, mode="walk_in", capacity=capacity
    )


def grid(ready, *rules, schedule=None):
    """Make the weekly grid of the schedule be ``rules`` (the reception changes it)."""
    schedule_id = (schedule or ready.schedule).sysid
    with ready.as_user(ready.a.reception) as actor:
        revision = service().schedule(actor=actor, schedule_id=schedule_id).revision
        return service().set_availability(actor=actor, schedule_id=schedule_id, rules=rules, expected_revision=revision)


@pytest.fixture
def ready(clinic):
    """Mondays: walk-in from 08:00 to 12:00, booked time from 14:00 to 18:00. Tuesdays: walk-in in the morning."""
    ready = prepare(clinic)
    grid(ready, walk_in(), AFTERNOON, walk_in(weekday=1))
    return ready


def arrive(ready, hour=9, *, key, **extra):
    """A walk-in booking in the Monday morning session; ``hour`` is any time of the period."""
    return book(ready, hour, key=key, mode="walk_in", **extra)


def step(ready, name, appointment, user=None, **extra):
    with ready.as_user(user or ready.a.reception) as actor:
        return getattr(service(), name)(
            actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision, **extra
        )


def cancel(ready, appointment):
    return step(ready, "cancel", appointment, reason="patient")


def queue(ready, user=None, day=None, organization=None, schedule=None):
    with ready.as_user(user or ready.a.reception, organization or ready.org_a) as actor:
        return service().queue(actor=actor, schedule_id=(schedule or ready.schedule).sysid, date=day or ready.monday)


def detail(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return service().appointment(actor=actor, appointment_id=appointment.sysid)


def session_event(ready, minute=480, day=None, schedule=None):
    key = f"session:{(schedule or ready.schedule).sysid}:{day or ready.monday:%Y%m%d}:{minute}"
    with ready.as_user(ready.a.reception) as actor:
        return CalendarService().managed_event(actor=actor, source_app="med_scheduling", source_key=key)


def own_event(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return CalendarService().managed_event(
            actor=actor, source_app="med_scheduling", source_key=str(appointment.sysid)
        )


def code_of(error):
    return error.value.code


# ------------------------------------------------------------------------------------ booking


def test_a_walk_in_booking_takes_the_bounds_of_its_period(ready, subtests):
    with capture_events() as events:
        first = arrive(ready, 9, key="a")
    with subtests.test("no time of its own: the period, with the planned duration"):
        assert (first.starts_at, first.ends_at) == (at(ready, 8), at(ready, 12))
        assert (first.mode, first.duration_minutes, first.arrival_number) == ("walk_in", 30, None)
        assert first.status == "scheduled" and not first.is_fit_in
    with subtests.test("any instant of the period leads to the same session"):
        last_minute = book(ready, 11, 59, key="b", mode="walk_in", duration_minutes=45)
        assert (last_minute.starts_at, last_minute.ends_at) == (first.starts_at, first.ends_at)
        assert last_minute.duration_minutes == 45
    with subtests.test("the event says the mode"):
        payload = dict(events[0].data)
        assert events[0].event_type == "med_scheduling.appointment_booked" and payload["mode"] == "walk_in"
        assert payload["starts_at"] == first.starts_at.isoformat()
    with subtests.test("the same key gives the same appointment"):
        assert arrive(ready, 10, key="a").sysid == first.sysid
    with subtests.test("booked time says its mode and its duration too"):
        timed = book(ready, 15)
        assert (timed.mode, timed.duration_minutes, timed.arrival_number) == ("booked", 30, None)
        assert timed.starts_at == at(ready, 15)


def test_the_mode_of_a_booking_is_explicit(ready, subtests):
    with subtests.test("a time inside a walk-in period"):
        with pytest.raises(Conflict) as error:
            book(ready, 9)
        assert code_of(error) == "mode_mismatch"
    with subtests.test("a time that crosses into a walk-in period"):
        grid(ready, walk_in(), AvailabilityRuleInput(0, 12 * 60, 18 * 60, START))
        with pytest.raises(Conflict) as error:
            book(ready, 11, 45)
        assert code_of(error) == "mode_mismatch"
    with subtests.test("no time inside a period of booked time"):
        with pytest.raises(Conflict) as error:
            book(ready, 15, mode="walk_in")
        assert code_of(error) == "mode_mismatch"
    with subtests.test("out of every period it is the grid that refuses"):
        for mode in ("booked", "walk_in"):
            with pytest.raises(Conflict) as error:
                book(ready, 19, mode=mode)
            assert code_of(error) == "slot_unavailable"
    with subtests.test("the end of the period is out of it"):
        with pytest.raises(Conflict) as error:
            book(ready, 12, mode="walk_in", key="noon")
        assert code_of(error) == "mode_mismatch"  # 12:00 already is booked time in this grid.
    with subtests.test("an unknown mode"):
        for mode in ("queue", None, 1):
            with pytest.raises(InvalidInput) as invalid:
                book(ready, 9, mode=mode)
            assert "mode" in invalid.value.errors
    with subtests.test("a fit-in with a time is taken inside a walk-in period"):
        squeezed = book(ready, 9, fit_in=True, key="fit")
        assert (squeezed.mode, squeezed.starts_at, squeezed.is_fit_in) == ("booked", at(ready, 9), True)
        assert own_event(ready, squeezed).title == f"Consulta · {squeezed.code}"
        assert queue(ready)[0].taken == 0


def test_a_session_takes_its_capacity(ready, subtests):
    grid(ready, walk_in(capacity=2), AFTERNOON)
    first = arrive(ready, key="a")
    arrive(ready, key="b")
    with subtests.test("the booking after the last place is refused"):
        with pytest.raises(Conflict) as error:
            arrive(ready, key="c")
        assert code_of(error) == "session_full"
        (session,) = queue(ready)
        assert (session.capacity, session.taken, session.is_full) == (2, 2, True)
    with subtests.test("a fit-in goes over the capacity and takes no place"):
        extra = arrive(ready, key="extra", fit_in=True)
        assert extra.is_fit_in and extra.mode == "walk_in"
        assert queue(ready)[0].taken == 2
    with subtests.test("cancelling frees the place"):
        cancel(ready, first)
        (session,) = queue(ready)
        assert (session.taken, session.is_full) == (1, False)
        assert arrive(ready, key="c").status == "scheduled"
        with pytest.raises(Conflict) as error:
            arrive(ready, key="d")
        assert code_of(error) == "session_full"
    with subtests.test("another day of the same period has its own places"):
        next_week = at(ready, 9) + timedelta(days=7)
        with ready.as_user(ready.a.reception) as actor:
            later = service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=next_week,
                mode="walk_in",
                idempotency_key="next-week",
            )
        assert later.starts_at == at(ready, 8) + timedelta(days=7)


def test_without_a_capacity_the_planned_minutes_fill_the_period(ready, subtests):
    grid(ready, walk_in(8, 9), AFTERNOON)
    arrive(ready, 8, key="a")
    with subtests.test("what still fits"):
        with pytest.raises(Conflict) as error:
            arrive(ready, 8, key="long", duration_minutes=35)
        assert code_of(error) == "session_full"
        assert arrive(ready, 8, key="b").duration_minutes == 30
    with subtests.test("not even the shortest one"):
        with pytest.raises(Conflict) as error:
            arrive(ready, 8, key="c", duration_minutes=5)
        assert code_of(error) == "session_full"
        (session,) = queue(ready)
        assert (session.planned_minutes, session.open_minutes, session.is_full) == (60, 60, True)
        assert session.capacity is None


def test_a_block_is_never_skipped(ready, subtests):
    def block(start, end, key):
        with ready.as_user(ready.a.reception) as actor:
            return service().add_block(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                starts_at=at(ready, *start),
                ends_at=at(ready, *end),
                idempotency_key=key,
            )

    grid(ready, walk_in(8, 9), AFTERNOON, walk_in(weekday=1))
    part = block((8, 30), (9, 0), "part")
    with subtests.test("a block over part of the period shortens it"):
        arrive(ready, 8, key="a")
        with pytest.raises(Conflict) as error:
            arrive(ready, 8, key="b", duration_minutes=5)
        assert code_of(error) == "session_full"
        (session,) = queue(ready)
        assert (session.open_minutes, session.is_full) == (30, True)
    with subtests.test("a block over the whole period closes it, for a fit-in too"):
        with ready.as_user(ready.a.reception) as actor:
            service().remove_block(actor=actor, block_id=part.sysid, expected_revision=part.revision)
        block((7, 0), (10, 0), "whole")
        for extra in ({}, {"fit_in": True}):
            with pytest.raises(Conflict) as error:
                arrive(ready, 8, key="closed", **extra)
            assert code_of(error) == "slot_unavailable"


def test_the_session_shares_the_room_of_its_schedule(ready, subtests):
    with as_admin(ready) as admin:
        room = service().add_room(actor=admin, name="Sala 1", idempotency_key="sala")
        rooms = {}
        for name in ("one", "two"):
            rooms[name] = service().create_schedule(
                actor=admin,
                name=f"Agenda da sala {name}",
                room_id=room.sysid,
                writer_group_ids=(ready.a.groups["reception"],),
                idempotency_key=f"room-{name}",
            )
    grid(ready, walk_in(), schedule=rooms["one"])
    grid(ready, AvailabilityRuleInput(0, 8 * 60, 18 * 60, START), schedule=rooms["two"])
    first = arrive(ready, key="a", schedule_id=rooms["one"].sysid)
    with subtests.test("two appointments of the session do not dispute the room"):
        second = arrive(ready, key="b", schedule_id=rooms["one"].sysid)
        assert first.room_id == second.room_id == room.sysid
    with subtests.test("a fit-in with a time in the session does not either"):
        assert book(ready, 9, key="fit", fit_in=True, schedule_id=rooms["one"].sysid).room_id == room.sysid
        assert arrive(ready, key="c", schedule_id=rooms["one"].sysid).status == "scheduled"
    with subtests.test("another schedule of the same room does"):
        with pytest.raises(Conflict) as error:
            book(ready, 9, key="other", schedule_id=rooms["two"].sysid)
        assert code_of(error) == "room_unavailable"
        assert book(ready, 13, key="after", schedule_id=rooms["two"].sysid).room_id == room.sysid
    with subtests.test("and a session does not start over an appointment of another schedule"):
        grid(ready, walk_in(12, 16), schedule=rooms["one"])
        with pytest.raises(Conflict) as error:
            book(ready, 12, key="late", mode="walk_in", schedule_id=rooms["one"].sysid)
        assert code_of(error) == "room_unavailable"


def test_the_kind_must_be_taken_in_the_mode_and_by_the_period(ready, subtests):
    with as_admin(ready) as admin:
        insured = service().add_appointment_type(
            actor=admin, code="unimed", name="Unimed", duration_minutes=20, idempotency_key="unimed"
        )

    def configure(*types):
        with ready.as_user(ready.a.reception) as actor:
            revision = service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
            service().set_schedule_types(
                actor=actor, schedule_id=ready.schedule.sysid, types=types, expected_revision=revision
            )

    def take(kind, hour=9, key="k", **extra):
        with ready.as_user(ready.a.reception) as actor:
            return service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=kind.sysid,
                starts_at=at(ready, hour),
                idempotency_key=key,
                **extra,
            )

    with subtests.test("a kind the period does not list"):
        grid(ready, walk_in(kinds=(insured.sysid,)), AFTERNOON)
        with pytest.raises(Conflict) as error:
            take(ready.kind, mode="walk_in")
        assert code_of(error) == "type_not_allowed"
        assert take(insured, key="listed", mode="walk_in").duration_minutes == 20
    with subtests.test("a fit-in skips the list of the period"):
        assert take(ready.kind, key="fit", mode="walk_in", fit_in=True).mode == "walk_in"
    configure(ScheduleTypeInput(ready.kind.sysid, allow_walk_in=False), ScheduleTypeInput(insured.sysid, 25))
    with subtests.test("a kind the schedule takes only at a booked time"):
        grid(ready, walk_in(), AFTERNOON)
        for extra in ({}, {"fit_in": True}):
            with pytest.raises(Conflict) as error:
                take(ready.kind, key="booked-only", mode="walk_in", **extra)
            assert code_of(error) == "type_not_allowed"
        assert take(ready.kind, 15, key="timed").mode == "booked"
        assert take(insured, key="own", mode="walk_in").duration_minutes == 25
    with subtests.test("the grid refuses to list it in a walk-in period"):
        with pytest.raises(InvalidInput) as invalid:
            grid(ready, walk_in(kinds=(ready.kind.sysid,)), AFTERNOON)
        assert "appointment_type_ids" in invalid.value.errors
        with pytest.raises(InvalidInput):  # Changing the mode of a period checks every kind it lists.
            grid(ready, walk_in(), AvailabilityRuleInput(0, 14 * 60, 18 * 60, START, None, (ready.kind.sysid,)))
            grid(
                ready,
                walk_in(),
                AvailabilityRuleInput(
                    0, 14 * 60, 18 * 60, START, appointment_type_ids=(ready.kind.sysid,), mode="walk_in"
                ),
            )


# ---------------------------------------------------------------------------------- the queue


def test_arrivals_are_numbered_in_the_session(ready, subtests):
    booked = [arrive(ready, key=name) for name in "abc"]
    with subtests.test("in the order of arrival, not of booking"):
        numbers = [step(ready, "check_in", booked[index]).arrival_number for index in (1, 0, 2)]
        assert numbers == [1, 2, 3]
        (session,) = queue(ready)
        assert [entry.appointment.sysid for entry in session.waiting] == [
            booked[1].sysid,
            booked[0].sysid,
            booked[2].sysid,
        ]
        assert [entry.position for entry in session.waiting] == [1, 2, 3]
        assert all(entry.arrived_at and not entry.is_priority for entry in session.waiting)
        assert session.expected == () and session.in_progress == ()
    with subtests.test("the number of a cancelled appointment is not given again"):
        last = queue(ready)[0].waiting[2].appointment
        assert cancel(ready, last).arrival_number == 3
        late = step(ready, "check_in", arrive(ready, key="d"))
        assert late.arrival_number == 4
    with subtests.test("another session starts from one"):
        tuesday = at(ready, 9) + timedelta(days=1)
        with ready.as_user(ready.a.reception) as actor:
            other = service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=tuesday,
                mode="walk_in",
                idempotency_key="tuesday",
            )
        assert step(ready, "check_in", other).arrival_number == 1
    with subtests.test("booked time has no arrival number"):
        assert step(ready, "check_in", book(ready, 15)).arrival_number is None


def test_the_queue_tells_who_waits_who_is_expected_and_who_was_seen(ready):
    waiting, expected, seen, missing_start, gone = (arrive(ready, key=name) for name in "abcde")
    step(ready, "check_in", waiting)
    confirmed = step(ready, "confirm", expected)
    in_room = step(ready, "start", step(ready, "check_in", missing_start), user=ready.a.doctor)
    done = step(ready, "complete", step(ready, "check_in", seen), user=ready.a.doctor)
    cancel(ready, gone)
    (monday, *_others) = queue(ready)
    assert [entry.appointment.sysid for entry in monday.waiting] == [waiting.sysid]
    assert [(entry.appointment.sysid, entry.position) for entry in monday.expected] == [(confirmed.sysid, None)]
    assert [entry.appointment.sysid for entry in monday.in_progress] == [in_room.sysid]
    assert [entry.appointment.status for entry in monday.finished] == ["completed"] and done.status == "completed"
    assert (monday.taken, monday.day, monday.starts_at, monday.ends_at) == (
        4,
        ready.monday,
        at(ready, 8),
        at(ready, 12),
    )
    # A day with a walk-in period and nobody booked still has its (empty) session; a day without one has none.
    (tuesday,) = queue(ready, day=ready.monday + timedelta(days=1))
    assert (tuesday.taken, tuesday.waiting, tuesday.expected) == (0, (), ())
    assert queue(ready, day=ready.monday + timedelta(days=2)) == ()


def test_priority_goes_first_and_is_fixed_with_cas(ready, subtests):
    first, second, third = (arrive(ready, key=name) for name in "abc")
    step(ready, "check_in", first)
    step(ready, "check_in", second)
    elder = step(ready, "check_in", third, priority=True)

    def order():
        return [(entry.appointment.arrival_number, entry.is_priority) for entry in queue(ready)[0].waiting]

    with subtests.test("the priority one is called before those who arrived earlier"):
        assert order() == [(3, True), (1, False), (2, False)]
        assert detail(ready, elder).is_priority and not detail(ready, first).is_priority
    with subtests.test("the mark is taken off, and the arrival number stays"):
        fixed = step(ready, "set_priority", elder, priority=False)
        assert order() == [(1, False), (2, False), (3, False)] and fixed.arrival_number == 3
    with subtests.test("with CAS"):

        def mark(priority):
            return lambda: step(ready, "set_priority", fixed, priority=priority)

        assert_cas_conflict(mark(True), mark(False), reread=order)
        assert order()[0] == (3, True)
    with subtests.test("before the arrival too, and the arrival keeps it"):
        fourth = step(ready, "set_priority", arrive(ready, key="d"), priority=True)
        assert step(ready, "check_in", fourth).arrival_number == 4
        assert order()[:2] == [(3, True), (4, True)]
    with subtests.test("only true or false"):
        for name, extra in (("set_priority", {"priority": "yes"}), ("check_in", {"priority": 1})):
            with pytest.raises(InvalidInput) as invalid:
                step(ready, name, arrive(ready, key=f"bad-{name}"), **extra)
            assert "priority" in invalid.value.errors
    with subtests.test("not once the care started"):
        started = step(ready, "start", queue(ready)[0].waiting[0].appointment, user=ready.a.doctor)
        with pytest.raises(Conflict) as error:
            step(ready, "set_priority", started, priority=False)
        assert code_of(error) == "invalid_transition"


def test_a_stale_arrival_gives_no_number(ready):
    appointment = arrive(ready, key="a")
    step(ready, "confirm", appointment)
    with pytest.raises(Conflict) as error:
        step(ready, "check_in", appointment)  # The revision from before the confirmation.
    assert code_of(error) == "stale_revision"
    (session,) = queue(ready)
    assert session.waiting == () and session.expected[0].appointment.arrival_number is None


def test_the_database_refuses_a_repeated_arrival_number(ready):
    first, second = arrive(ready, key="a"), arrive(ready, key="b")
    step(ready, "check_in", first)

    def write(**values):
        # A plain queryset, without the validation of the core's: the constraints of the database answer.
        return QuerySet(Appointment).filter(pk=second.sysid).update(revision=F("revision") + 1, **values)

    with ready.as_user(ready.a.reception):
        with pytest.raises(ValidationError):  # The model refuses it before the database does.
            Appointment.objects.filter(pk=second.sysid).update(arrival_number=1)
        with pytest.raises(IntegrityError, match="med_scheduling_appointment_arrival_number"), transaction.atomic():
            write(arrival_number=1)
        # A number is of a walk-in appointment only.
        with pytest.raises(IntegrityError, match="med_scheduling_appointment_arrival"), transaction.atomic():
            write(mode="booked", arrival_number=7)
        assert write(arrival_number=2) == 1


def test_arrival_locks_the_schedule_before_the_appointment(ready):
    appointment = arrive(ready, key="a")
    with CaptureQueriesContext(connection) as queries:
        step(ready, "check_in", appointment)
    locked = []
    for query in queries.captured_queries:
        sql = query["sql"]
        if "FOR UPDATE" in sql and " FROM " in sql:
            locked.append(sql.split(" FROM ", 1)[1].split('"')[1].removeprefix("med_scheduling_"))
    assert [table for table in locked if table in ("schedule", "appointment")][:2] == ["schedule", "appointment"]


def test_no_show_only_after_the_end_of_the_period(ready):
    future = arrive(ready, key="future")
    with pytest.raises(Conflict) as error:
        step(ready, "mark_no_show", future)
    assert code_of(error) == "invalid_transition"
    now = timezone.now().astimezone(SP)
    yesterday = (now - timedelta(days=1)).date()
    grid(ready, walk_in(0, 24, weekday=yesterday.weekday()), walk_in(0, 24, weekday=now.weekday()))

    def take(day, key):
        with ready.as_user(ready.a.reception) as actor:
            return service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=datetime(day.year, day.month, day.day, 12, tzinfo=SP),
                mode="walk_in",
                idempotency_key=key,
            )

    with pytest.raises(Conflict) as error:  # The period started, and it has not ended.
        step(ready, "mark_no_show", take(now.date(), "today"))
    assert code_of(error) == "invalid_transition"
    assert step(ready, "mark_no_show", take(yesterday, "yesterday")).status == "no_show"


# -------------------------------------------------------------------------------- reschedule


def move(ready, appointment, hour, *, days=0, **extra):
    with ready.as_user(ready.a.reception) as actor:
        return service().reschedule(
            actor=actor,
            appointment_id=appointment.sysid,
            starts_at=at(ready, hour) + timedelta(days=days),
            expected_revision=appointment.revision,
            **extra,
        )


def test_reschedule_between_sessions_and_modes(ready, subtests):
    appointment = step(ready, "confirm", book(ready, 9, key="a", mode="walk_in", duration_minutes=40))
    arrive(ready, key="stays")
    with subtests.test("to another session it keeps the mode, the code and the planned duration"):
        with capture_events() as events:
            moved = move(ready, appointment, 10, days=1)
        assert (moved.starts_at, moved.ends_at) == (at(ready, 8) + timedelta(days=1), at(ready, 12) + timedelta(days=1))
        assert (moved.code, moved.mode, moved.duration_minutes) == (appointment.code, "walk_in", 40)
        assert (moved.status, moved.arrival_number) == ("scheduled", None)
        assert [event.event_type.rsplit("_", 1)[1] for event in events] == ["rescheduled"]
        assert dict(events[0].data)["mode"] == "walk_in"
        assert session_event(ready).title == "Ordem de chegada · 1 paciente"
        assert session_event(ready, day=ready.monday + timedelta(days=1)).title == "Ordem de chegada · 1 paciente"
    with subtests.test("to a booked time it gets a time and an event of its own"):
        timed = move(ready, moved, 15, mode="booked")
        assert (timed.mode, timed.starts_at, timed.ends_at) == ("booked", at(ready, 15), at(ready, 15, 40))
        assert own_event(ready, timed).starts_at == at(ready, 15)
        assert session_event(ready, day=ready.monday + timedelta(days=1)) is None
    with subtests.test("the mode it has is the one it keeps"):
        with pytest.raises(Conflict) as error:
            move(ready, timed, 9)
        assert code_of(error) == "mode_mismatch"
    with subtests.test("back to a session: its own event goes away"):
        back = move(ready, timed, 9, mode="walk_in")
        assert (back.mode, back.starts_at, back.duration_minutes) == ("walk_in", at(ready, 8), 40)
        assert own_event(ready, back) is None
        assert session_event(ready).title == "Ordem de chegada · 2 pacientes"
    with subtests.test("a full session refuses it, and a move inside its own session does not count itself"):
        grid(ready, walk_in(capacity=2), AFTERNOON, walk_in(weekday=1, capacity=1))
        assert move(ready, back, 11).starts_at == at(ready, 8)
        with ready.as_user(ready.a.reception) as actor:
            service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=at(ready, 9) + timedelta(days=1),
                mode="walk_in",
                idempotency_key="tuesday",
            )
        current = detail(ready, back).appointment
        with pytest.raises(Conflict) as error:
            move(ready, current, 9, days=1)
        assert code_of(error) == "session_full"
    with subtests.test("who already arrived is not moved, in either direction"):
        arrived = step(ready, "check_in", detail(ready, back).appointment)
        for extra in ({}, {"mode": "booked"}):
            with pytest.raises(Conflict) as error:
                move(ready, arrived, 15, **extra)
            assert code_of(error) == "invalid_transition"
        timed_arrival = step(ready, "check_in", book(ready, 16, key="timed"))
        with pytest.raises(Conflict) as error:
            move(ready, timed_arrival, 9, mode="walk_in")
        assert code_of(error) == "invalid_transition"
        assert move(ready, timed_arrival, 17).starts_at == at(ready, 17)  # Booked time moves as before.


def test_reschedule_to_another_schedule_keeps_the_mode(ready):
    with as_admin(ready) as admin:
        other = service().create_schedule(
            actor=admin,
            name="Outra agenda",
            professional_id=ready.doctor.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            idempotency_key="other",
        )
    grid(ready, walk_in(14, 18), schedule=other)
    appointment = arrive(ready, key="a")
    with capture_events() as events:
        moved = move(ready, appointment, 15, schedule_id=other.sysid)
    assert [event.event_type.rsplit("_", 1)[1] for event in events] == ["cancelled", "booked"]
    assert (moved.mode, moved.schedule_id, moved.starts_at) == ("walk_in", other.sysid, at(ready, 14))
    assert moved.rescheduled_from_id == appointment.sysid and moved.code != appointment.code
    assert session_event(ready) is None
    assert session_event(ready, minute=14 * 60, schedule=other).title == "Ordem de chegada · 1 paciente"


# ---------------------------------------------------------------------------------- calendar


def test_the_calendar_has_one_event_per_session(ready, subtests):
    first, second = arrive(ready, key="a"), arrive(ready, key="b")
    event = session_event(ready)
    with subtests.test("how many, never who"):
        assert event.title == "Ordem de chegada · 2 pacientes"
        assert (event.starts_at, event.ends_at) == (at(ready, 8), at(ready, 12))
        shown = f"{event.title} {event.source_path}"
        assert not [word for word in ("Maria", "Secreta", first.code, second.code) if word in shown]
        assert event.source_path == f"apps/med_scheduling/schedules/{ready.schedule.sysid}/queue/{ready.monday}/"
    with subtests.test("no appointment of the session has an event of its own"):
        assert own_event(ready, first) is None and own_event(ready, second) is None
    with subtests.test("the professional of the schedule attends the session"):
        with ready.as_user(ready.a.doctor) as actor:
            busy = CalendarService().free_busy(
                actor=actor,
                user_ids=(ready.a.doctor.pk,),
                start=at(ready, 8),
                end=at(ready, 12),
                include_attending=True,
            )
        assert [(block.starts_at, block.ends_at) for block in busy] == [(at(ready, 8), at(ready, 12))]
    with subtests.test("the session stays while its patients are seen"):
        seen = step(ready, "complete", step(ready, "check_in", first), user=ready.a.doctor)
        assert seen.status == "completed" and session_event(ready).title == "Ordem de chegada · 2 pacientes"
    with subtests.test("a cancellation counts one less, and the last one removes the event"):
        third = arrive(ready, key="c")
        assert session_event(ready).title == "Ordem de chegada · 3 pacientes"
        cancel(ready, third)
        cancel(ready, second)
        assert session_event(ready).title == "Ordem de chegada · 1 paciente"
    with subtests.test("an empty session has no event"):
        lonely = book(ready, 9, key="tuesday", mode="walk_in")  # The same Monday session: now two again.
        cancel(ready, lonely)
        tuesday = ready.monday + timedelta(days=1)
        assert session_event(ready, day=tuesday) is None
        with ready.as_user(ready.a.reception) as actor:
            only = service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=at(ready, 9) + timedelta(days=1),
                mode="walk_in",
                idempotency_key="only",
            )
        assert session_event(ready, day=tuesday).title == "Ordem de chegada · 1 paciente"
        cancel(ready, only)
        assert session_event(ready, day=tuesday) is None


# ----------------------------------------------------------------------------------- privacy


def test_the_priority_mark_leaves_only_in_the_queue_and_in_the_detail(ready, subtests):
    appointment = arrive(ready, key="a")
    with capture_events() as events:
        arrived = step(ready, "check_in", appointment, priority=True)
        step(ready, "set_priority", arrived, priority=False)
        marked = step(ready, "set_priority", detail(ready, arrived).appointment, priority=True)
    with subtests.test("not in the appointment of the lists"):
        assert "is_priority" not in {field.name for field in fields(AppointmentInfo)}
        assert not [name for name in dir(marked) if "priority" in name]
    with subtests.test("not in an event: setting the mark publishes nothing"):
        assert [event.event_type.rsplit("_", 1)[1] for event in events] == ["arrived"]
        assert not [name for name in dict(events[0].data) if "priority" in name]
        assert dict(events[0].data)["mode"] == "walk_in"
    with subtests.test("not in the notification of the arrival"):
        run_pending_jobs()
        with ready.as_user(ready.a.doctor) as actor:
            (notice,) = NotificationService().inbox(actor=actor).items
        assert {value.name for value in notice.payload} == {"code", "starts_at"}
    with subtests.test("redacted in the audit"):
        with as_admin(ready) as admin:
            entries = (
                AuditService()
                .history(actor=admin, table_key="med_scheduling.appointment", record_id=appointment.sysid)
                .items
            )
        marks = [change for entry in entries for change in entry.changes if change.name == "is_priority"]
        assert marks and all(change.redacted for change in marks)
        assert {str(value) for change in marks for value in (change.old, change.new)} <= {"[REDACTED]", "None"}
    with subtests.test("in the detail and in the queue"):
        assert detail(ready, marked).is_priority
        assert queue(ready)[0].waiting[0].is_priority


def test_who_reads_the_schedule_reads_its_queue(ready, subtests):
    arrive(ready, key="a")
    for name in ("reception", "doctor"):
        with subtests.test(name):
            (session, *_rest) = queue(ready, user=getattr(ready.a, name))
            assert session.taken == 1
            with ready.as_user(getattr(ready.a, name)) as actor:
                plan = service().day_plan(
                    actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
                )
            assert [period.mode for period in plan] == ["walk_in", "booked"]
    with subtests.test("who does not read the schedule"):
        with pytest.raises(NotFound):
            queue(ready, user=ready.a.finance)
        with ready.as_user(ready.a.finance) as actor, pytest.raises(NotFound):
            service().day_plan(
                actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
            )
    with subtests.test("organization B"):
        with pytest.raises(NotFound):
            queue(ready, user=ready.b.admin, organization=ready.org_b)
    with subtests.test("who only reads does not register an arrival nor set the priority"):
        with as_admin(ready) as admin:
            current = service().schedule(actor=admin, schedule_id=ready.schedule.sysid)
            service().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(ready.a.groups["reception"],),
                reader_group_ids=(ready.a.groups["finance"],),
                expected_revision=current.revision,
            )
        (session, *_rest) = queue(ready, user=ready.a.finance)
        waiting = session.expected[0].appointment
        from skeleton.service_api import Forbidden

        for name, extra in (("check_in", {}), ("set_priority", {"priority": True})):
            with pytest.raises(Forbidden):
                step(ready, name, waiting, user=ready.a.finance, **extra)
    with subtests.test("an invalid day"):
        with pytest.raises(InvalidInput):
            queue(ready, day="2026-06-01")


# ------------------------------------------------------------------------------ plan and day


def test_the_plan_of_the_days_tells_what_each_period_holds(ready, subtests):
    grid(ready, walk_in(capacity=2, kinds=(ready.kind.sysid,)), AFTERNOON, walk_in(weekday=1))
    arrive(ready, key="a")
    arrive(ready, key="b", duration_minutes=45)
    arrive(ready, key="fit", fit_in=True)
    cancel(ready, arrive(ready, key="gone", fit_in=True))
    book(ready, 15)
    with ready.as_user(ready.a.doctor) as actor:
        plan = service().day_plan(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            start_date=ready.monday,
            end_date=ready.monday + timedelta(days=2),
        )
    morning, afternoon, tuesday = plan
    with subtests.test("a walk-in period with its places"):
        assert (morning.mode, morning.capacity, morning.appointment_type_ids) == ("walk_in", 2, (ready.kind.sysid,))
        assert (morning.taken, morning.planned_minutes, morning.open_minutes, morning.is_full) == (2, 75, 240, True)
        assert (morning.day, morning.start_minute, morning.end_minute) == (ready.monday, 480, 720)
        assert (morning.starts_at, morning.ends_at) == (at(ready, 8), at(ready, 12))
        assert not morning.is_exception
    with subtests.test("a period of booked time"):
        assert (afternoon.mode, afternoon.capacity, afternoon.appointment_type_ids) == ("booked", None, ())
        assert (afternoon.taken, afternoon.planned_minutes, afternoon.is_full) == (1, 30, False)
    with subtests.test("another day"):
        assert (tuesday.day, tuesday.mode, tuesday.taken, tuesday.is_full) == (
            ready.monday + timedelta(days=1),
            "walk_in",
            0,
            False,
        )
    with subtests.test("at most 62 days, in order"):
        with ready.as_user(ready.a.doctor) as actor:
            for start, end in (
                (ready.monday, ready.monday + timedelta(days=62)),
                (ready.monday, ready.monday - timedelta(days=1)),
            ):
                with pytest.raises(InvalidInput):
                    service().day_plan(actor=actor, schedule_id=ready.schedule.sysid, start_date=start, end_date=end)


def test_the_day_shows_the_sessions_and_only_booked_time_has_free_slots(ready, subtests):
    def day():
        with ready.as_user(ready.a.reception) as actor:
            (agenda,) = service().day(actor=actor, date=ready.monday)
        return agenda

    step(ready, "check_in", arrive(ready, key="a"), priority=True)
    arrive(ready, key="b")
    timed = book(ready, 15)
    agenda = day()
    with subtests.test("the session with its queue"):
        (session,) = agenda.sessions
        assert (session.taken, len(session.waiting), len(session.expected)) == (2, 1, 1)
        assert session.waiting[0].is_priority and session.waiting[0].appointment.arrival_number == 1
    with subtests.test("every appointment of the day, each saying its mode"):
        assert [item.mode for item in agenda.appointments] == ["walk_in", "walk_in", "booked"]
    with subtests.test("free slots only in the booked time"):
        free = [f"{slot.starts_at.astimezone(SP):%H:%M}" for slot in agenda.free]
        assert free == ["14:00", "14:30", "15:30", "16:00", "16:30", "17:00", "17:30"]
        assert timed.starts_at == at(ready, 15)
        with ready.as_user(ready.a.reception) as actor:
            found = service().available_slots(
                actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
            )
        assert [f"{slot.starts_at.astimezone(SP):%H:%M}" for slot in found] == free
    with subtests.test("the number of queries does not grow with the queue"):
        with ready.as_user(ready.a.reception) as actor:
            with CaptureQueriesContext(connection) as few:
                service().day(actor=actor, date=ready.monday)
        for name in "cdef":
            step(ready, "check_in", arrive(ready, key=name))
        with ready.as_user(ready.a.reception) as actor:
            with CaptureQueriesContext(connection) as many:
                (agenda,) = service().day(actor=actor, date=ready.monday)
        assert len(agenda.sessions[0].waiting) == 5 and len(many) == len(few)


def test_a_session_whose_period_left_the_grid_still_shows(ready):
    appointment = step(ready, "check_in", arrive(ready, key="a"))
    grid(ready, AFTERNOON)
    (session,) = queue(ready)
    assert [entry.appointment.sysid for entry in session.waiting] == [appointment.sysid]
    assert (session.starts_at, session.ends_at, session.capacity) == (at(ready, 8), at(ready, 12), None)
    assert step(ready, "complete", appointment, user=ready.a.doctor).status == "completed"


def test_book_from_the_waitlist_into_a_session(ready):
    other = new_patient(ready, full_name="Outra Paciente")
    with ready.as_user(ready.a.reception) as actor:
        entry = service().add_to_waitlist(
            actor=actor,
            patient_id=other.sysid,
            earliest_date=date(2026, 1, 1),
            appointment_type_id=ready.kind.sysid,
            idempotency_key="wait",
        )
        with pytest.raises(Conflict) as error:
            service().book_from_waitlist(
                actor=actor,
                entry_id=entry.sysid,
                schedule_id=ready.schedule.sysid,
                starts_at=at(ready, 9),
                expected_revision=entry.revision,
                idempotency_key="from-wait",
            )
        assert code_of(error) == "mode_mismatch"
        booked = service().book_from_waitlist(
            actor=actor,
            entry_id=entry.sysid,
            schedule_id=ready.schedule.sysid,
            starts_at=at(ready, 9),
            expected_revision=entry.revision,
            idempotency_key="from-wait",
            mode="walk_in",
        )
    assert (booked.mode, booked.patient_id, booked.starts_at) == ("walk_in", other.sysid, at(ready, 8))
