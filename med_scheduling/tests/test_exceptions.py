"""The exception of a day: its periods in place of the weekly grid, the conversion of the booked appointments
and the weekly grid that refuses a change of mode under them."""

from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.events import capture_events
from skeleton.testing.service_api import assert_cas_conflict

from ..service_api import AvailabilityRuleInput, DayWindowInput, SchedulingService
from .booking import SP, at, book, prepare
from .helpers import as_admin, new_patient

START = date(2026, 1, 1)
MORNING = AvailabilityRuleInput(0, 8 * 60, 12 * 60, START)


def service():
    return SchedulingService()


def walk_in_rule(start=8, end=12, *, weekday=1, **extra):
    return AvailabilityRuleInput(weekday, start * 60, end * 60, START, mode="walk_in", **extra)


def window(start=8, end=12, **extra):
    return DayWindowInput(start * 60, end * 60, **extra)


def session(start=8, end=12, **extra):
    return window(start, end, mode="walk_in", **extra)


def revision(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision


def grid(ready, *rules):
    current = revision(ready)
    with ready.as_user(ready.a.reception) as actor:
        return service().set_availability(
            actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=current
        )


def weekly(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().availability(actor=actor, schedule_id=ready.schedule.sysid)


@pytest.fixture
def ready(clinic):
    """Mondays: booked time from 08:00 to 12:00. Tuesdays: walk-in from 08:00 to 12:00."""
    ready = prepare(clinic)
    grid(ready, MORNING, walk_in_rule())
    ready.tuesday = ready.monday + timedelta(days=1)
    return ready


def change(ready, *windows, day=None, user=None, organization=None, expected_revision=None, **extra):
    current = revision(ready) if expected_revision is None else expected_revision
    with ready.as_user(user or ready.a.reception, organization or ready.org_a) as actor:
        return service().set_day_exception(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            date=day or ready.monday,
            windows=windows,
            expected_revision=current,
            **extra,
        )


def clear(ready, day=None, user=None, expected_revision=None, **extra):
    current = revision(ready) if expected_revision is None else expected_revision
    with ready.as_user(user or ready.a.reception) as actor:
        return service().clear_day_exception(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            date=day or ready.monday,
            expected_revision=current,
            **extra,
        )


def preview(ready, *windows, day=None, user=None, organization=None):
    """What the change would do; without windows, what going back to the weekly grid would."""
    with ready.as_user(user or ready.a.reception, organization or ready.org_a) as actor:
        return service().plan_conflicts(
            actor=actor, schedule_id=ready.schedule.sysid, date=day or ready.monday, windows=windows or None
        )


def exceptions(ready, user=None, **extra):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().day_exceptions(actor=actor, schedule_id=ready.schedule.sysid, **extra)


def plan(ready, day=None):
    day = day or ready.monday
    with ready.as_user(ready.a.reception) as actor:
        found = service().day_plan(actor=actor, schedule_id=ready.schedule.sysid, start_date=day, end_date=day)
    return [(item.start_minute, item.end_minute, item.mode, item.capacity, item.is_exception) for item in found]


def free_hours(ready, day=None):
    day = day or ready.monday
    with ready.as_user(ready.a.reception) as actor:
        found = service().available_slots(
            actor=actor, schedule_id=ready.schedule.sysid, start_date=day, end_date=day, appointment_type_id=None
        )
    return [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in found]


def detail(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return service().appointment(actor=actor, appointment_id=appointment.sysid).appointment


def step(ready, name, appointment, user=None, **extra):
    current = detail(ready, appointment)
    with ready.as_user(user or ready.a.reception) as actor:
        return getattr(service(), name)(
            actor=actor, appointment_id=current.sysid, expected_revision=current.revision, **extra
        )


def on_tuesday(ready, key, hour=9, **extra):
    """A walk-in booking in the Tuesday morning session."""
    with ready.as_user(ready.a.reception) as actor:
        return service().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            starts_at=at(ready, hour, day=ready.tuesday),
            mode="walk_in",
            idempotency_key=key,
            **extra,
        )


def queue(ready, day=None):
    with ready.as_user(ready.a.reception) as actor:
        return service().queue(actor=actor, schedule_id=ready.schedule.sysid, date=day or ready.monday)


def event_of(ready, key):
    with ready.as_user(ready.a.reception) as actor:
        return CalendarService().managed_event(actor=actor, source_app="med_scheduling", source_key=str(key))


def session_event(ready, minute=480, day=None):
    return event_of(ready, f"session:{ready.schedule.sysid}:{day or ready.monday:%Y%m%d}:{minute}")


def reasons(found):
    return [(item.appointment.code, item.reason, item.blocking) for item in found]


def code_of(error):
    return error.value.code


# --------------------------------------------------------------------------- the periods of a day


def test_the_exception_replaces_the_weekly_grid_on_its_day(ready, subtests):
    following = ready.monday + timedelta(days=7)
    with subtests.test("the day follows its own periods; the Monday after, the grid"):
        made = change(ready, window(14, 16))
        assert (made.schedule_id, made.date) == (ready.schedule.sysid, ready.monday)
        (only,) = made.windows
        assert (only.start_minute, only.end_minute, only.mode, only.on_date) == (840, 960, "booked", ready.monday)
        assert (only.weekday, only.valid_from, only.valid_until) == (0, ready.monday, ready.monday)
        assert plan(ready) == [(840, 960, "booked", None, True)]
        assert plan(ready, following) == [(480, 720, "booked", None, False)]
        assert free_hours(ready) == ["14:00", "14:30", "15:00", "15:30"]
        assert free_hours(ready, following)[0] == "08:00"
    with subtests.test("booking follows the exception"):
        with pytest.raises(Conflict) as refused:
            book(ready, 9)
        assert code_of(refused) == "slot_unavailable"
        afternoon = book(ready, 14, key="afternoon")
        assert afternoon.starts_at == at(ready, 14)
    with subtests.test("the weekly grid does not list the exception"):
        assert [(rule.weekday, rule.on_date) for rule in weekly(ready)] == [(0, None), (1, None)]
    with subtests.test("another change replaces the periods of the day"):
        kind = ready.kind.sysid
        made = change(ready, window(14, 16), session(16, 18, capacity=3, appointment_type_ids=(kind,)))
        assert [(item.start_minute, item.mode, item.capacity, item.appointment_type_ids) for item in made.windows] == [
            (840, "booked", None, ()),
            (960, "walk_in", 3, (kind,)),
        ]
        assert made.windows[0].sysid == only.sysid, "a period that stays keeps its row"
        assert plan(ready) == [(840, 960, "booked", None, True), (960, 1080, "walk_in", 3, True)]
    with subtests.test("the days with an exception, from today on"):
        change(ready, session(8, 12), day=ready.tuesday + timedelta(days=7))
        found = exceptions(ready)
        assert [(item.date, len(item.windows)) for item in found] == [
            (ready.monday, 2),
            (ready.tuesday + timedelta(days=7), 1),
        ]
        assert [item.date for item in exceptions(ready, start_date=ready.tuesday)] == [found[1].date]
        assert exceptions(ready, end_date=ready.monday) == found[:1]
    with subtests.test("going back to the weekly grid"):
        with pytest.raises(Conflict) as refused:
            clear(ready)  # The appointment of the afternoon has no place in the weekly grid.
        assert code_of(refused) == "plan_conflicts"
        step(ready, "cancel", afternoon, reason="patient")
        assert clear(ready) is None
        assert plan(ready) == [(480, 720, "booked", None, False)]
        assert [item.date for item in exceptions(ready)] == [ready.tuesday + timedelta(days=7)]
        clear(ready)  # A day without an exception stays as it is.
        assert plan(ready) == [(480, 720, "booked", None, False)]


def test_the_exception_is_changed_with_the_revision_of_the_schedule(ready):
    before = revision(ready)
    change(ready, window(14, 16))
    assert revision(ready) > before
    current = revision(ready)
    assert_cas_conflict(
        lambda: change(ready, window(14, 17), expected_revision=current),
        lambda: change(ready, window(15, 18), expected_revision=current),
        reread=lambda: plan(ready),
    )
    assert plan(ready) == [(840, 1020, "booked", None, True)]
    with pytest.raises(Conflict) as stale:
        clear(ready, expected_revision=current)
    assert code_of(stale) == "stale_revision" and plan(ready) == [(840, 1020, "booked", None, True)]


def test_what_an_exception_refuses(ready, subtests):
    yesterday = timezone.localdate(timezone=SP) - timedelta(days=1)
    cases = {
        "no period: closing a day is a block": ((), {}, "windows"),
        "overlapping periods": ((window(8, 12), window(11, 13)), {}, "windows"),
        "more than 20 periods": (tuple(DayWindowInput(60 * hour, 60 * hour + 30) for hour in range(21)), {}, "windows"),
        "a window of the weekly grid": ((MORNING,), {}, "windows"),
        "a day that is over": ((window(),), {"day": yesterday}, "date"),
        "a moment instead of a day": ((window(),), {"day": datetime(2030, 1, 7, tzinfo=SP)}, "date"),
        "an end before the start": ((DayWindowInput(720, 480),), {}, "start_minute"),
        "beyond midnight": ((DayWindowInput(1380, 1500),), {}, "start_minute"),
        "an unknown mode": ((DayWindowInput(480, 720, mode="queue"),), {}, "mode"),
        "places in booked time": ((window(capacity=5),), {}, "capacity"),
        "no place at all": ((session(capacity=0),), {}, "capacity"),
    }
    before = revision(ready)
    for name, (windows, extra, field) in cases.items():
        with subtests.test(name), pytest.raises(InvalidInput) as invalid:
            change(ready, *windows, **extra)
        with subtests.test(name + ": the field"):
            assert set(invalid.value.errors) == {field}
    with subtests.test("a kind the schedule does not take in the mode of the period"):
        with as_admin(ready) as admin:
            other = service().add_appointment_type(actor=admin, code="exame", name="Exame", idempotency_key="exame")
            current = service().schedule(actor=admin, schedule_id=ready.schedule.sysid)
        from ..service_api import ScheduleTypeInput

        with ready.as_user(ready.a.reception) as actor:
            service().set_schedule_types(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                types=(
                    ScheduleTypeInput(ready.kind.sysid),
                    ScheduleTypeInput(other.sysid, None, True, False),
                ),
                expected_revision=current.revision,
            )
        before = revision(ready)
        with pytest.raises(InvalidInput) as invalid:
            change(ready, session(appointment_type_ids=(other.sysid,)))
        assert set(invalid.value.errors) == {"appointment_type_ids"}
        assert change(ready, window(appointment_type_ids=(other.sysid,))).windows[0].appointment_type_ids == (
            other.sysid,
        )
        clear(ready)
        before = revision(ready)
    with subtests.test("nothing was written"):
        assert revision(ready) == before and exceptions(ready) == ()
    with subtests.test("going back on a day that is over"):
        with pytest.raises(InvalidInput) as invalid:
            clear(ready, day=yesterday)
        assert set(invalid.value.errors) == {"date"}
    with subtests.test("an inverted interval of days"):
        with pytest.raises(InvalidInput):
            exceptions(ready, start_date=ready.tuesday, end_date=ready.monday)


def test_saving_the_weekly_grid_keeps_the_exceptions(ready):
    change(ready, session(14, 18, capacity=4))
    grid(ready, AvailabilityRuleInput(0, 9 * 60, 11 * 60, START), walk_in_rule(), walk_in_rule(weekday=3))
    assert plan(ready) == [(840, 1080, "walk_in", 4, True)]
    assert plan(ready, ready.monday + timedelta(days=7)) == [(540, 660, "booked", None, False)]
    assert [(item.date, len(item.windows)) for item in exceptions(ready)] == [(ready.monday, 1)]
    grid(ready)  # Not even an empty grid takes the exception away.
    assert plan(ready) == [(840, 1080, "walk_in", 4, True)] and weekly(ready) == ()


# --------------------------------------------------------------------------------- the conversion


def test_a_day_that_becomes_walk_in_takes_its_appointments_once_confirmed(ready, subtests):
    first = book(ready, 9, key="first")
    second = step(ready, "confirm", book(ready, 10, key="second", patient_id=new_patient(ready).sysid))
    squeezed = book(ready, 12, 30, key="fit", fit_in=True, patient_id=new_patient(ready).sysid)
    gone = step(ready, "cancel", book(ready, 11, key="gone", patient_id=new_patient(ready).sysid), reason="patient")
    before = revision(ready)
    with subtests.test("the preview lists what moves, and what the move ignores"):
        found = preview(ready, session(capacity=1))
        assert reasons(found) == [(first.code, "to_walk_in", False), (second.code, "to_walk_in", False)]
        assert {(item.starts_at, item.ends_at) for item in found} == {(at(ready, 8), at(ready, 12))}
        assert [(item.over_capacity, item.kind_not_listed) for item in found] == [(True, False), (True, False)]
        assert [item.over_capacity for item in preview(ready, session(capacity=2))] == [False, False]
        assert [item.over_capacity for item in preview(ready, session(8, 9))] == [False, False]
    with subtests.test("without the confirmation nothing changes"):
        with pytest.raises(Conflict) as refused:
            change(ready, session(capacity=15))
        assert code_of(refused) == "plan_conflicts"
        assert revision(ready) == before and plan(ready) == [(480, 720, "booked", None, False)]
        assert detail(ready, first).starts_at == at(ready, 9) and detail(ready, second).status == "confirmed"
    with subtests.test("confirmed with the list seen, the appointments go to the session"):
        ids = (first.sysid, second.sysid)
        with capture_events() as events:
            change(ready, session(capacity=15), convert_existing=True, expected_affected=ids)
        assert plan(ready) == [(480, 720, "walk_in", 15, True)]
        moved = [detail(ready, first), detail(ready, second)]
        assert [(row.code, row.mode, row.starts_at, row.ends_at) for row in moved] == [
            (first.code, "walk_in", at(ready, 8), at(ready, 12)),
            (second.code, "walk_in", at(ready, 8), at(ready, 12)),
        ]
        assert [(row.status, row.duration_minutes, row.arrival_number) for row in moved] == [
            ("scheduled", 30, None),
            ("scheduled", 30, None),
        ]
        published = [event for event in events if event.event_type == "med_scheduling.appointment_rescheduled"]
        assert {event.record_sysid for event in published} == set(ids)
        assert {dict(event.data)["mode"] for event in published} == {"walk_in"}
        assert not [event for event in events if "priority" in repr(event.data) or "Maria" in repr(event.data)]
    with subtests.test("the calendar has the session in place of each appointment"):
        assert event_of(ready, first.sysid) is None and event_of(ready, second.sysid) is None
        assert session_event(ready).title == "Ordem de chegada · 2 pacientes"
    with subtests.test("the queue of the day expects them"):
        (found,) = queue(ready)
        assert (found.capacity, found.taken) == (15, 2)
        assert {entry.appointment.sysid for entry in found.expected} == set(ids)
    with subtests.test("the fit-in with a time and the cancelled one stay as they were"):
        kept = detail(ready, squeezed)
        assert (kept.mode, kept.starts_at) == ("booked", at(ready, 12, 30)) and event_of(ready, squeezed.sysid)
        assert (detail(ready, gone).mode, detail(ready, gone).status) == ("booked", "cancelled")
    with subtests.test("saving the same periods again moves nobody"):
        assert preview(ready, session(capacity=15)) == ()
        change(ready, session(capacity=20))
        assert plan(ready) == [(480, 720, "walk_in", 20, True)]


def test_a_booking_made_after_the_preview_asks_for_another_look(ready, subtests):
    first = book(ready, 9, key="first")
    seen = tuple(item.appointment.sysid for item in preview(ready, session()))
    assert seen == (first.sysid,)
    late = book(ready, 10, key="late", patient_id=new_patient(ready).sysid)
    before = revision(ready)
    with subtests.test("the list changed: nothing is moved"):
        with pytest.raises(Conflict) as changed:
            change(ready, session(), convert_existing=True, expected_affected=seen)
        assert code_of(changed) == "plan_changed"
        assert revision(ready) == before and detail(ready, first).mode == detail(ready, late).mode == "booked"
    with subtests.test("an appointment that left the list changes it too"):
        step(ready, "cancel", late, reason="patient")
        with pytest.raises(Conflict) as changed:
            change(ready, session(), convert_existing=True, expected_affected=(first.sysid, late.sysid))
        assert code_of(changed) == "plan_changed"
    with subtests.test("the confirmation says what was seen"):
        for wrong in (None, [first.sysid], "all"):
            with pytest.raises(InvalidInput) as invalid:
                change(ready, session(), convert_existing=True, expected_affected=wrong)
            assert set(invalid.value.errors) == {"expected_affected"}
        with pytest.raises(InvalidInput) as invalid:
            change(ready, session(), convert_existing="yes", expected_affected=seen)
        assert set(invalid.value.errors) == {"convert_existing"}
    with subtests.test("with the list of now the day changes"):
        change(ready, session(), convert_existing=True, expected_affected=seen)
        assert detail(ready, first).mode == "walk_in"
    with subtests.test("a confirmation with nothing to move takes an empty list"):
        change(ready, session(capacity=9), convert_existing=True, expected_affected=())
        with pytest.raises(Conflict) as changed:
            change(ready, session(capacity=8), convert_existing=True, expected_affected=seen)
        assert code_of(changed) == "plan_changed"


def test_what_no_confirmation_overcomes(ready, subtests):
    def refused(*windows, day=None, **extra):
        ids = tuple(item.appointment.sysid for item in preview(ready, *windows, day=day) if not item.blocking)
        with pytest.raises(Conflict) as error:
            change(ready, *windows, day=day, convert_existing=True, expected_affected=ids, **extra)
        return code_of(error)

    with subtests.test("an appointment outside the new periods"):
        timed = book(ready, 9, key="timed")
        assert reasons(preview(ready, window(14, 18))) == [(timed.code, "outside", True)]
        assert reasons(preview(ready, DayWindowInput(480, 555))) == [(timed.code, "outside", True)]
        assert refused(window(14, 18)) == "plan_conflicts" and plan(ready) == [(480, 720, "booked", None, False)]
        assert preview(ready, window(9, 10)) == ()
    with subtests.test("a walk-in session that would become booked time"):
        walker = on_tuesday(ready, "walker")
        assert reasons(preview(ready, window(), day=ready.tuesday)) == [(walker.code, "to_booked", True)]
        assert refused(window(), day=ready.tuesday) == "plan_conflicts"
        assert detail(ready, walker).mode == "walk_in"
    with subtests.test("a session that changes its bounds takes who has not arrived"):
        found = preview(ready, session(8, 13), day=ready.tuesday)
        assert reasons(found) == [(walker.code, "to_session", False)]
        change(ready, session(8, 13), day=ready.tuesday, convert_existing=True, expected_affected=(walker.sysid,))
        moved = detail(ready, walker)
        assert (moved.starts_at, moved.ends_at) == (at(ready, 8, day=ready.tuesday), at(ready, 13, day=ready.tuesday))
        assert session_event(ready, day=ready.tuesday).title == "Ordem de chegada · 1 paciente"
    with subtests.test("a session with an arrival registered keeps its bounds"):
        arrived = step(ready, "check_in", walker)
        assert arrived.arrival_number == 1
        assert reasons(preview(ready, session(8, 12), day=ready.tuesday)) == [(walker.code, "arrived", True)]
        assert refused(session(8, 12), day=ready.tuesday) == "plan_conflicts"
        # The capacity and the kinds of the same period may change: the session stays.
        change(ready, session(8, 13, capacity=7), day=ready.tuesday)
        assert detail(ready, walker).arrival_number == 1
    with subtests.test("who arrived for a time is not taken to a session"):
        step(ready, "check_in", timed)
        assert reasons(preview(ready, session())) == [(timed.code, "arrived", True)]
        assert refused(session()) == "plan_conflicts"
    with subtests.test("an appointment being attended is not touched"):
        step(ready, "start", timed, user=ready.a.doctor)
        assert preview(ready, session()) == ()
        change(ready, session())
        kept = detail(ready, timed)
        assert (kept.mode, kept.status, kept.starts_at) == ("booked", "in_progress", at(ready, 9))


def test_going_back_to_the_weekly_grid_follows_the_same_rules(ready, subtests):
    change(ready, session(8, 12), window(14, 18))
    walker = book(ready, 9, key="walker", mode="walk_in")
    timed = book(ready, 14, key="timed", patient_id=new_patient(ready).sysid)
    with subtests.test("what the weekly grid does not hold"):
        assert reasons(preview(ready)) == [(walker.code, "to_booked", True), (timed.code, "outside", True)]
        with pytest.raises(Conflict) as refused:
            clear(ready, convert_existing=True, expected_affected=())
        assert code_of(refused) == "plan_conflicts" and len(plan(ready)) == 2
    with subtests.test("once they are out of the way the day follows the grid again"):
        step(ready, "cancel", walker, reason="patient")
        step(ready, "cancel", timed, reason="patient")
        assert preview(ready) == ()
        clear(ready)
        assert plan(ready) == [(480, 720, "booked", None, False)]
    with subtests.test("going back to a walk-in grid moves the appointments with a time"):
        change(ready, window(), day=ready.tuesday)
        moving = book(ready, 9, key="moving")
        with ready.as_user(ready.a.reception) as actor:
            moving = service().reschedule(
                actor=actor,
                appointment_id=moving.sysid,
                starts_at=at(ready, 9, day=ready.tuesday),
                expected_revision=moving.revision,
            )
        assert reasons(preview(ready, day=ready.tuesday)) == [(moving.code, "to_walk_in", False)]
        with pytest.raises(Conflict) as refused:
            clear(ready, day=ready.tuesday)
        assert code_of(refused) == "plan_conflicts"
        clear(ready, day=ready.tuesday, convert_existing=True, expected_affected=(moving.sysid,))
        assert detail(ready, moving).mode == "walk_in" and plan(ready, ready.tuesday)[0][4] is False


# ------------------------------------------------------------------------------ the weekly grid


def test_the_weekly_grid_refuses_a_change_of_mode_under_appointments(ready, subtests):
    timed = book(ready, 9, key="timed")
    walker = on_tuesday(ready, "walker")
    to_walk_in = AvailabilityRuleInput(0, 8 * 60, 12 * 60, START, mode="walk_in")
    tuesday_booked = AvailabilityRuleInput(1, 8 * 60, 12 * 60, START)

    def conflicts(*rules):
        with ready.as_user(ready.a.reception) as actor:
            return service().availability_conflicts(actor=actor, schedule_id=ready.schedule.sysid, rules=rules)

    before = revision(ready)
    with subtests.test("booked time that would become walk-in"):
        assert reasons(conflicts(to_walk_in, walk_in_rule())) == [(timed.code, "to_walk_in", False)]
        with pytest.raises(Conflict) as refused:
            grid(ready, to_walk_in, walk_in_rule())
        assert code_of(refused) == "plan_conflicts" and f"{ready.monday:%d/%m/%Y}" in str(refused.value.detail)
    with subtests.test("a session that would become booked time"):
        assert reasons(conflicts(MORNING, tuesday_booked)) == [(walker.code, "to_booked", True)]
        with pytest.raises(Conflict) as refused:
            grid(ready, MORNING, tuesday_booked)
        assert code_of(refused) == "plan_conflicts" and f"{ready.tuesday:%d/%m/%Y}" in str(refused.value.detail)
    with subtests.test("nothing was written"):
        assert revision(ready) == before and [rule.mode for rule in weekly(ready)] == ["booked", "walk_in"]
    with subtests.test("the change passes when it holds from after the last appointment"):
        until = AvailabilityRuleInput(0, 8 * 60, 12 * 60, START, ready.monday)
        later = AvailabilityRuleInput(0, 8 * 60, 12 * 60, ready.monday + timedelta(days=1), mode="walk_in")
        assert conflicts(until, later, walk_in_rule()) == ()
        grid(ready, until, later, walk_in_rule())
        assert plan(ready) == [(480, 720, "booked", None, False)]
        assert plan(ready, ready.monday + timedelta(days=7)) == [(480, 720, "walk_in", None, False)]
        assert detail(ready, timed).mode == "booked"
    with subtests.test("a day changed on its own does not count for the grid"):
        change(ready, session(), convert_existing=True, expected_affected=(timed.sysid,))
        grid(ready, to_walk_in, walk_in_rule())
        assert detail(ready, timed).mode == "walk_in"
    with subtests.test("taking a period out of the grid converts nobody and is not refused"):
        grid(ready, to_walk_in)
        assert detail(ready, walker).mode == "walk_in" and len(queue(ready, ready.tuesday)) == 1
    with subtests.test("the session of the changed day does not hold the grid either"):
        assert conflicts(MORNING) == ()
        grid(ready, MORNING)
        assert detail(ready, timed).mode == "walk_in" and plan(ready) == [(480, 720, "walk_in", None, True)]


# ------------------------------------------------------------------------------- authorization


def test_who_changes_the_schedule_changes_its_days(ready, subtests):
    book(ready, 9, key="timed")
    with subtests.test("the doctor of the schedule reads the days and the preview"):
        assert exceptions(ready, user=ready.a.doctor) == ()
        assert len(preview(ready, session(), user=ready.a.doctor)) == 1
    with subtests.test("who does not read the schedule"):
        for call in (
            lambda: exceptions(ready, user=ready.a.finance),
            lambda: preview(ready, session(), user=ready.a.finance),
            lambda: change(ready, window(14, 18), user=ready.a.finance),
            lambda: clear(ready, user=ready.a.finance),
        ):
            with pytest.raises(NotFound):
                call()
    with subtests.test("organization B"):
        with pytest.raises(NotFound):
            preview(ready, session(), user=ready.b.admin, organization=ready.org_b)
        with pytest.raises(NotFound):
            change(ready, window(14, 18), user=ready.b.admin, organization=ready.org_b)
    with subtests.test("who only reads the schedule sees and changes nothing"):
        with as_admin(ready) as admin:
            current = service().schedule(actor=admin, schedule_id=ready.schedule.sysid)
            service().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(ready.a.groups["reception"],),
                reader_group_ids=(ready.a.groups["finance"],),
                expected_revision=current.revision,
            )
        assert len(preview(ready, session(), user=ready.a.finance)) == 1
        with pytest.raises(Forbidden):
            change(ready, window(14, 18), user=ready.a.finance)
        with pytest.raises(Forbidden):
            clear(ready, user=ready.a.finance)
    with subtests.test("nothing changed"):
        assert exceptions(ready) == () and plan(ready) == [(480, 720, "booked", None, False)]
