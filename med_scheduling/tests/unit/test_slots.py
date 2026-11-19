"""Free slots: windows, durations, blocks, appointments, validity, daylight saving, horizon and past."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from ...slots import Window, compute_slots, fits_grid, localize

SP = "America/Sao_Paulo"
MONDAY = date(2026, 6, 1)  # A Monday.
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def local(day, hour, minute=0, zone=SP):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone))


def slots(
    windows, taken=(), *, start=MONDAY, end=MONDAY, slot=30, duration=30, zone=SP, now=NOW, horizon=365, kind=None
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
