"""The plan of a day: periods as instants, the session of an instant, open minutes and the room of a session."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from ...plan import BOOKED, WALK_IN, instant, is_full, local_day, open_minutes, period_at, periods_on
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
