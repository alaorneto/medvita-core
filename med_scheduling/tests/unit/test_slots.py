"""Free slots: windows, durations, blocks, appointments, kinds, validity, daylight saving, horizon and past."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from ...slots import Window, collide, compute_slots, fits_grid, localize, typed_slots, windows_of, windows_on

SP = "America/Sao_Paulo"
MONDAY = date(2026, 6, 1)  # A Monday.
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def local(day, hour, minute=0, zone=SP):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone))


def slots(
    windows,
    taken=(),
    *,
    start=MONDAY,
    end=MONDAY,
    slot=30,
    duration=30,
    zone=SP,
    now=NOW,
    horizon=365,
    kind=None,
    any_type=False,
):
    found = compute_slots(
        windows=windows,
        taken=list(taken),
        start_date=start,
        end_date=end,
        slot_minutes=slot,
        duration_minutes=duration,
        timezone=zone,
        now=now,
        horizon_days=horizon,
        appointment_type_id=kind,
        any_type=any_type,
    )
    return [start.astimezone(ZoneInfo(zone)).strftime("%H:%M") for start, _end in found]


def morning(**extra):
    return Window(weekday=0, start_minute=8 * 60, end_minute=10 * 60, valid_from=date(2026, 1, 1), **extra)


def test_cases(subtests):
    afternoon = Window(0, 14 * 60, 15 * 60, date(2026, 1, 1))
    cases = {
        "simple grid": (slots([morning()]), ["08:00", "08:30", "09:00", "09:30"]),
        "two windows": (slots([morning(), afternoon]), ["08:00", "08:30", "09:00", "09:30", "14:00", "14:30"]),
        "duration longer than the slot": (slots([morning()], duration=60), ["08:00", "08:30", "09:00"]),
        "partial block": (
            slots([morning()], taken=[(local(MONDAY, 8, 30), local(MONDAY, 9, 15))]),
            ["08:00", "09:30"],
        ),
        "another weekday": (slots([Window(1, 480, 600, date(2026, 1, 1))]), []),
        "validity ended": (slots([morning(valid_until=date(2026, 5, 31))]), []),
        "validity starts later": (slots([Window(0, 480, 600, date(2026, 6, 2))]), []),
        "past": (slots([morning()], now=local(MONDAY, 9, 0)), ["09:00", "09:30"]),
        "beyond the horizon": (slots([morning()], now=MONDAY_NOW - timedelta(days=10), horizon=5), []),
    }
    for name, (found, expected) in cases.items():
        with subtests.test(name):
            assert found == expected


MONDAY_NOW = local(MONDAY, 0)


def test_window_restricted_to_a_type():
    kind = uuid4()
    window = morning(appointment_type_id=kind)
    assert slots([window], kind=kind) == ["08:00", "08:30", "09:00", "09:30"]
    assert slots([window], kind=uuid4()) == [] and slots([window]) == []


def test_any_type_includes_the_restricted_windows():
    restricted = morning(appointment_type_id=uuid4())
    afternoon = Window(0, 14 * 60, 15 * 60, date(2026, 1, 1), appointment_type_id=uuid4())
    assert slots([restricted, afternoon], any_type=True) == ["08:00", "08:30", "09:00", "09:30", "14:00", "14:30"]
    assert slots([restricted, morning()], any_type=True) == ["08:00", "08:30", "09:00", "09:30"]


def test_daylight_saving_in_new_york():
    zone = "America/New_York"
    spring = date(2026, 3, 8)  # Clocks jump from 02:00 to 03:00.
    window = Window(spring.weekday(), 60, 4 * 60, date(2026, 1, 1))
    assert slots([window], start=spring, end=spring, zone=zone) == ["01:00", "01:30", "03:00", "03:30"]
    autumn = date(2026, 11, 1)  # Clocks go back from 02:00 to 01:00: 01:00 to 02:00 happens twice.
    window = Window(autumn.weekday(), 60, 2 * 60, date(2026, 1, 1))
    found = compute_slots(
        windows=[window],
        taken=[],
        start_date=autumn,
        end_date=autumn,
        slot_minutes=30,
        duration_minutes=30,
        timezone=zone,
        now=NOW,
        horizon_days=400,
    )
    assert [start.astimezone(ZoneInfo(zone)).fold for start, _ in found] == [0, 0]
    assert localize(datetime(2026, 3, 8, 2, 30), ZoneInfo(zone)) is None


def test_fits_grid():
    windows = [morning()]
    assert fits_grid(windows, local(MONDAY, 8), local(MONDAY, 9), timezone=SP)
    assert not fits_grid(windows, local(MONDAY, 9, 30), local(MONDAY, 10, 30), timezone=SP)
    assert not fits_grid(windows, local(MONDAY, 7, 30), local(MONDAY, 8), timezone=SP)
    assert not fits_grid(
        windows, local(MONDAY + timedelta(days=1), 8), local(MONDAY + timedelta(days=1), 9), timezone=SP
    )


def test_a_window_takes_the_kinds_of_its_set(subtests):
    first, second, other = uuid4(), uuid4(), uuid4()
    window = morning(appointment_type_ids=frozenset({first, second}))
    hours = ["08:00", "08:30", "09:00", "09:30"]
    with subtests.test("a kind of the set"):
        assert slots([window], kind=first) == slots([window], kind=second) == hours
    with subtests.test("a kind out of the set, and no kind at all"):
        assert slots([window], kind=other) == [] and slots([window]) == []
    with subtests.test("any type asks for every window"):
        assert slots([window], any_type=True) == hours
    with subtests.test("the single kind of an older window joins the set"):
        joined = morning(appointment_type_id=other, appointment_type_ids=frozenset({first}))
        assert joined.types == {first, other}
        assert slots([joined], kind=other) == slots([joined], kind=first) == hours
        assert slots([joined], kind=second) == []
    with subtests.test("a window built as before takes every kind"):
        plain = Window(0, 8 * 60, 10 * 60, date(2026, 1, 1))
        assert plain.types == frozenset() and plain.appointment_type_ids == frozenset()
        assert slots([plain], kind=other) == slots([plain]) == hours
    with subtests.test("booking inside the grid asks the same question"):
        assert fits_grid([window], local(MONDAY, 8), local(MONDAY, 9), timezone=SP, appointment_type_id=first)
        assert not fits_grid([window], local(MONDAY, 8), local(MONDAY, 9), timezone=SP, appointment_type_id=other)
        assert not fits_grid([window], local(MONDAY, 8), local(MONDAY, 9), timezone=SP)


def test_each_free_slot_says_the_kinds_of_its_window():
    first, second = uuid4(), uuid4()
    restricted = morning(appointment_type_ids=frozenset({first, second}))
    open_window = Window(0, 14 * 60, 15 * 60, date(2026, 1, 1))
    arguments = {
        "windows": [restricted, open_window],
        "taken": [],
        "start_date": MONDAY,
        "end_date": MONDAY,
        "slot_minutes": 60,
        "duration_minutes": 60,
        "timezone": SP,
        "now": NOW,
        "horizon_days": 365,
    }
    found = typed_slots(**arguments, any_type=True)
    assert [kinds for _start, _end, kinds in found] == [{first, second}, {first, second}, frozenset()]
    assert compute_slots(**arguments, any_type=True) == [(start, end) for start, end, _kinds in found]
    assert [kinds for _start, _end, kinds in typed_slots(**arguments, appointment_type_id=first)] == [
        {first, second},
        {first, second},
        frozenset(),
    ]


def test_windows_take_the_kinds_listed_for_their_rules():
    first, second, legacy = uuid4(), uuid4(), uuid4()

    def rule(pk, appointment_type_id=None):
        return SimpleNamespace(
            pk=pk,
            weekday=0,
            start_minute=480,
            end_minute=600,
            valid_from=date(2026, 1, 1),
            valid_until=None,
            appointment_type_id=appointment_type_id,
        )

    listed, plain, older = rule(uuid4()), rule(uuid4()), rule(uuid4(), legacy)
    windows = windows_of([listed, plain, older], {listed.pk: [first, second], older.pk: [first]})
    assert [window.types for window in windows] == [{first, second}, frozenset(), {first, legacy}]
    assert [window.types for window in windows_of([listed, older])] == [frozenset(), {legacy}]


def test_two_windows_collide_when_weekday_minutes_and_validity_cross(subtests):
    def window(start, end, weekday=0, valid_from=date(2026, 1, 1), valid_until=None):
        return Window(weekday, start, end, valid_from, valid_until)

    base = window(480, 720)
    cases = {
        "the same minutes": (window(480, 720), True),
        "one inside the other": (window(540, 600), True),
        "crossing the end": (window(660, 780), True),
        "touching ends": (window(720, 780), False),
        "before": (window(420, 480), False),
        "another weekday": (window(480, 720, weekday=1), False),
        "valid only before": (window(480, 720, valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31)), False),
        "valid until the first day of the other": (
            window(480, 720, valid_from=date(2025, 1, 1), valid_until=date(2026, 1, 1)),
            True,
        ),
        "valid later, without an end": (window(480, 720, valid_from=date(2030, 1, 1)), True),
    }
    for name, (other, expected) in cases.items():
        with subtests.test(name):
            assert collide(base, other) is expected and collide(other, base) is expected
    with subtests.test("an ended window and one that starts after it"):
        ended = window(480, 720, valid_until=date(2026, 6, 30))
        assert not collide(ended, window(480, 720, valid_from=date(2026, 7, 1)))


def test_the_exception_of_a_day_replaces_the_weekly_grid_on_that_day_only(subtests):
    weekly = Window(0, 480, 720, date(2026, 1, 1))
    own = Window(0, 840, 960, MONDAY, MONDAY, on_date=MONDAY)
    windows = [weekly, own]
    following = MONDAY + timedelta(days=7)

    def hours(found):
        return [int(label[:2]) for label in found]

    with subtests.test("the day follows its exception; the Monday after, the grid"):
        assert windows_on(windows, MONDAY) == [own] and windows_on(windows, following) == [weekly]
        assert windows_on(windows, MONDAY + timedelta(days=1)) == []
    with subtests.test("the free slots of the two Mondays"):
        assert hours(slots(windows, slot=60, duration=60)) == [14, 15]
        assert hours(slots(windows, start=following, end=following, slot=60, duration=60)) == [8, 9, 10, 11]
    with subtests.test("a time of the weekly grid is out of the grid on the day of the exception"):
        assert not fits_grid(windows, local(MONDAY, 9), local(MONDAY, 10), timezone=SP)
        assert fits_grid(windows, local(MONDAY, 14), local(MONDAY, 15), timezone=SP)
        assert fits_grid(windows, local(following, 9), local(following, 10), timezone=SP)
    with subtests.test("the exception may list kinds and be of the other mode"):
        kind = uuid4()
        typed = [weekly, Window(0, 840, 960, MONDAY, MONDAY, appointment_type_ids=frozenset({kind}), on_date=MONDAY)]
        assert hours(slots(typed, slot=60, duration=60)) == []
        assert hours(slots(typed, slot=60, duration=60, kind=kind)) == [14, 15]
        walk_in = [weekly, Window(0, 480, 720, MONDAY, MONDAY, mode="walk_in", on_date=MONDAY)]
        assert slots(walk_in) == [] and len(slots(walk_in, start=following, end=following)) == 8
    with subtests.test("a window of an exception collides only with another of the same day"):
        assert not collide(weekly, Window(0, 480, 720, MONDAY, MONDAY, on_date=MONDAY))
        assert collide(own, Window(0, 900, 1020, MONDAY, MONDAY, on_date=MONDAY))
        assert not collide(own, Window(0, 840, 960, following, following, on_date=following))
    with subtests.test("the rows of the exception carry their day into the windows"):
        row = SimpleNamespace(
            pk=uuid4(),
            weekday=0,
            start_minute=840,
            end_minute=960,
            valid_from=MONDAY,
            valid_until=MONDAY,
            appointment_type_id=None,
            mode="booked",
            capacity=None,
            on_date=MONDAY,
        )
        assert windows_of([row]) == [own]
