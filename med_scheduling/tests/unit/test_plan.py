"""The plan of a day: periods as instants, the session of an instant, open minutes and the room of a session."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from ...plan import (
    ARRIVED,
    BLOCKING,
    BOOKED,
    OUTSIDE,
    TO_BOOKED,
    TO_SESSION,
    TO_WALK_IN,
    WALK_IN,
    Booking,
    conflicts,
    instant,
    is_full,
    local_day,
    open_minutes,
    period_at,
    periods_on,
)
from ...slots import Window, compute_slots, fits_grid

SP = "America/Sao_Paulo"
MONDAY = date(2026, 6, 1)  # A Monday.
START = date(2026, 1, 1)


def local(day, hour, minute=0, zone=SP):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone))


def walk_in(start=8, end=12, weekday=0, capacity=None, kinds=frozenset(), **extra):
    return Window(
        weekday, start * 60, end * 60, START, appointment_type_ids=kinds, mode=WALK_IN, capacity=capacity, **extra
    )


def booked(start=14, end=18, weekday=0):
    return Window(weekday, start * 60, end * 60, START)


def test_the_periods_of_a_day_are_its_windows_as_instants(subtests):
    kind = uuid4()
    windows = [booked(), walk_in(capacity=15, kinds=frozenset({kind})), walk_in(weekday=1)]
    morning, afternoon = periods_on(windows, MONDAY, SP)
    with subtests.test("by start, each with its mode, capacity and kinds"):
        assert (morning.mode, morning.capacity, morning.kinds) == (WALK_IN, 15, {kind})
        assert (afternoon.mode, afternoon.capacity, afternoon.kinds) == (BOOKED, None, frozenset())
    with subtests.test("the bounds are instants in UTC"):
        assert (morning.starts_at, morning.ends_at) == (local(MONDAY, 8), local(MONDAY, 12))
        assert morning.starts_at.tzinfo is UTC and morning.minutes == 240
        assert (morning.day, morning.start_minute, morning.end_minute) == (MONDAY, 480, 720)
    with subtests.test("another weekday, and a validity that ended"):
        assert [period.mode for period in periods_on(windows, MONDAY + timedelta(days=1), SP)] == [WALK_IN]
        assert periods_on([walk_in(valid_until=date(2026, 5, 31))], MONDAY, SP) == []
    with subtests.test("a period that ends at midnight"):
        (late,) = periods_on([walk_in(start=20, end=24)], MONDAY, SP)
        assert late.ends_at == local(MONDAY + timedelta(days=1), 0) and late.minutes == 240
        assert local_day(late.starts_at, SP) == MONDAY


def test_the_session_of_an_instant(subtests):
    periods = periods_on([walk_in(), booked()], MONDAY, SP)
    morning, afternoon = periods
    cases = {
        "the start belongs to the period": (local(MONDAY, 8), None, morning),
        "the middle": (local(MONDAY, 10, 30), None, morning),
        "the end does not": (local(MONDAY, 12), None, None),
        "out of every period": (local(MONDAY, 13), None, None),
        "before the first": (local(MONDAY, 7, 59), None, None),
        "of the mode asked for": (local(MONDAY, 9), WALK_IN, morning),
        "of another mode": (local(MONDAY, 9), BOOKED, None),
        "booked time is a period too": (local(MONDAY, 15), None, afternoon),
        "booked time is no session": (local(MONDAY, 15), WALK_IN, None),
    }
    for name, (moment, mode, expected) in cases.items():
        with subtests.test(name):
            assert period_at(periods, moment, mode) == expected


def test_daylight_saving_keeps_the_minutes_that_really_pass(subtests):
    zone = "America/New_York"
    spring = date(2026, 3, 8)  # Clocks jump from 02:00 to 03:00.
    autumn = date(2026, 11, 1)  # Clocks go back from 02:00 to 01:00.
    with subtests.test("an hour that does not exist is not counted"):
        (period,) = periods_on([walk_in(start=1, end=4, weekday=spring.weekday())], spring, zone)
        assert period.minutes == 120
        assert period_at([period], local(spring, 3, 30, zone)) == period
    with subtests.test("a start that does not exist takes the instant the clock jumps to"):
        zone_info = ZoneInfo(zone)
        assert instant(spring, 150, zone_info) == local(spring, 3, 30, zone)
    with subtests.test("an hour that happens twice is counted twice"):
        (period,) = periods_on([walk_in(start=1, end=2, weekday=autumn.weekday())], autumn, zone)
        assert period.minutes == 120


def test_open_minutes_leave_out_what_the_blocks_take(subtests):
    (period,) = periods_on([walk_in()], MONDAY, SP)
    cases = {
        "no block": ([], 240),
        "a block inside": ([(local(MONDAY, 9), local(MONDAY, 10))], 180),
        "a block that crosses the start": ([(local(MONDAY, 7), local(MONDAY, 8, 30))], 210),
        "a block out of the period": ([(local(MONDAY, 13), local(MONDAY, 14))], 240),
        "two blocks that overlap count once": (
            [(local(MONDAY, 9), local(MONDAY, 10)), (local(MONDAY, 9, 30), local(MONDAY, 10, 30))],
            150,
        ),
        "one block inside another": (
            [(local(MONDAY, 9), local(MONDAY, 11)), (local(MONDAY, 9, 30), local(MONDAY, 10))],
            120,
        ),
        "the whole period": ([(local(MONDAY, 0), local(MONDAY, 23))], 0),
    }
    for name, (blocked, expected) in cases.items():
        with subtests.test(name):
            assert open_minutes(period, blocked) == expected


def test_a_session_is_full_by_its_capacity_or_by_its_minutes(subtests):
    (counted,) = periods_on([walk_in(capacity=2)], MONDAY, SP)
    (timed,) = periods_on([walk_in(start=8, end=9)], MONDAY, SP)
    with subtests.test("capacity counts appointments, whatever they last"):
        assert not is_full(counted, [], 480) and not is_full(counted, [30], 480)
        assert is_full(counted, [5, 5], 5)
    with subtests.test("without a capacity the planned minutes fill the period"):
        assert not is_full(timed, [30], 30)
        assert is_full(timed, [30], 31) and is_full(timed, [30, 30], 5)
    with subtests.test("a block shortens the period"):
        blocked = [(local(MONDAY, 8, 30), local(MONDAY, 9))]
        assert is_full(timed, [], 31, blocked=blocked) and not is_full(timed, [], 30, blocked=blocked)
    with subtests.test("a block does not change a capacity"):
        assert not is_full(counted, [30], 30, blocked=[(local(MONDAY, 8), local(MONDAY, 11, 55))])


def test_a_walk_in_window_gives_no_slot_and_is_out_of_the_booked_grid():
    windows = [walk_in(), booked()]
    found = compute_slots(
        windows=windows,
        taken=[],
        start_date=MONDAY,
        end_date=MONDAY,
        slot_minutes=60,
        duration_minutes=60,
        timezone=SP,
        now=datetime(2026, 1, 1, tzinfo=UTC),
        horizon_days=365,
        any_type=True,
    )
    assert [start.astimezone(ZoneInfo(SP)).hour for start, _end in found] == [14, 15, 16, 17]
    assert not fits_grid(windows, local(MONDAY, 9), local(MONDAY, 10), timezone=SP)
    assert fits_grid(windows, local(MONDAY, 14), local(MONDAY, 15), timezone=SP)


def test_the_periods_of_a_day_with_an_exception_are_the_ones_of_the_exception():
    own = Window(0, 14 * 60, 16 * 60, MONDAY, MONDAY, mode=WALK_IN, capacity=5, on_date=MONDAY)
    windows = [walk_in(), booked(), own]
    (period,) = periods_on(windows, MONDAY, SP)
    assert (period.start_minute, period.mode, period.capacity, period.is_exception) == (840, WALK_IN, 5, True)
    weekly = periods_on(windows, MONDAY + timedelta(days=7), SP)
    assert [(item.mode, item.is_exception) for item in weekly] == [(WALK_IN, False), (BOOKED, False)]


def test_a_new_plan_says_what_it_does_to_each_appointment(subtests):
    """The day had booked time from 08:00 to 12:00 and a walk-in session from 14:00 to 18:00."""

    def plan(*windows):
        return periods_on(list(windows), MONDAY, SP)

    def timed(key, hour, minutes=30, **extra):
        return Booking(key, BOOKED, local(MONDAY, hour), local(MONDAY, hour) + timedelta(minutes=minutes), **extra)

    def in_session(key, start=14, end=18, **extra):
        return Booking(key, WALK_IN, local(MONDAY, start), local(MONDAY, end), **extra)

    def reasons(periods, *bookings):
        return {booking.key: reason for booking, reason, _period in conflicts(periods, bookings)}

    same = plan(booked(8, 12), walk_in(14, 18))
    with subtests.test("the plan that holds everything changes nothing"):
        assert (
            conflicts(same, [timed("a", 9), timed("b", 11, 60), in_session("c"), in_session("d", arrived=True)]) == []
        )
    with subtests.test("a time inside a period that becomes walk-in goes to its session"):
        morning = plan(walk_in(8, 12), walk_in(14, 18))
        ((booking, reason, period),) = conflicts(morning, [timed("a", 9), in_session("c")])
        assert (booking.key, reason) == ("a", TO_WALK_IN)
        assert (period.starts_at, period.ends_at) == (local(MONDAY, 8), local(MONDAY, 12))
    with subtests.test("who already arrived is not taken to a session"):
        assert reasons(plan(walk_in(8, 12)), timed("a", 9, arrived=True)) == {"a": ARRIVED}
    with subtests.test("a session whose period changes its bounds follows it, unless somebody arrived"):
        longer = plan(booked(8, 12), walk_in(14, 19))
        found = conflicts(longer, [in_session("c"), in_session("d", arrived=True)])
        assert [(booking.key, reason) for booking, reason, _period in found] == [("c", TO_SESSION), ("d", ARRIVED)]
        assert found[0][2].ends_at == local(MONDAY, 19)
        earlier = plan(walk_in(13, 18))
        assert reasons(earlier, in_session("c")) == {"c": TO_SESSION}
    with subtests.test("a session whose period becomes booked time has no time to take"):
        assert reasons(plan(booked(8, 12), booked(14, 18)), in_session("c")) == {"c": TO_BOOKED}
    with subtests.test("no period of the new plan holds it"):
        only_morning = plan(booked(8, 10))
        assert reasons(only_morning, timed("a", 9), timed("b", 10), timed("e", 9, 90), in_session("c")) == {
            "b": OUTSIDE,
            "e": OUTSIDE,
            "c": OUTSIDE,
        }
    with subtests.test("only the moves pass with a confirmation"):
        assert BLOCKING == {TO_BOOKED, OUTSIDE, ARRIVED} and not BLOCKING & {TO_WALK_IN, TO_SESSION}
