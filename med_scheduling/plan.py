"""The plan of a day: the periods a schedule works and the sessions of the walk-in ones (pure, no database).

A period is a weekly window on one local day, with its bounds as instants. A period of booked
time gives slots (``slots.py``). A walk-in period makes a **session**: the appointments booked in
it have no time of their own, they share the bounds of the period and are seen in the order the
patients arrive (``queue.py``).

How many a session takes: its ``capacity`` when the period has one; otherwise the planned
durations add up to no more than the minutes the period is open, which are its minutes without
what the blocks of the schedule take.

When the plan of a day changes (the exception of a day, or the weekly grid), ``conflicts`` says
what happens to each appointment already booked: nothing, a move the owner has to confirm, or a
refusal of the change.

Daylight saving time: the bounds come from the local clock, so a period on the day the clock
changes lasts the minutes that really pass. A start that does not exist takes the instant the
clock jumps to.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from .slots import BOOKED, WALK_IN, Window, applies, windows_on

__all__ = [
    "ARRIVED",
    "BLOCKING",
    "BOOKED",
    "OUTSIDE",
    "TO_BOOKED",
    "TO_SESSION",
    "TO_WALK_IN",
    "WALK_IN",
    "Booking",
    "Period",
    "conflicts",
    "instant",
    "is_full",
    "local_day",
    "open_minutes",
    "period_at",
    "periods_on",
]

# What a new plan does to an appointment already booked.
TO_WALK_IN = "to_walk_in"  # had a time and its period becomes walk-in: goes to the session, once confirmed
TO_SESSION = "to_session"  # walk-in, and its period changes its bounds: follows the period, once confirmed
TO_BOOKED = "to_booked"  # walk-in, and its period becomes booked time: it has no time to take
OUTSIDE = "outside"  # no period of the new plan holds it
ARRIVED = "arrived"  # the patient already arrived: the queue keeps its numbers
# The reasons no confirmation overcomes.
BLOCKING = frozenset({TO_BOOKED, OUTSIDE, ARRIVED})


@dataclass(frozen=True)
class Period:
    """A window on one day: its minutes on the local clock and its bounds as instants (UTC)."""

    day: date
    start_minute: int
    end_minute: int
    starts_at: datetime
    ends_at: datetime
    mode: str = BOOKED
    capacity: int | None = None
    kinds: frozenset[UUID] = frozenset()
    is_exception: bool = False  # of the exception of its day, not of the weekly grid

    @property
    def minutes(self) -> int:
        """The minutes that really pass between the bounds."""
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


def instant(day: date, minute: int, zone: ZoneInfo) -> datetime:
    """The instant of a minute of the local day (1440 is the midnight that ends it)."""
    local = datetime.combine(day, time()) + timedelta(minutes=minute)
    return local.replace(tzinfo=zone).astimezone(UTC)


def local_day(moment: datetime, timezone: str) -> date:
    return moment.astimezone(ZoneInfo(timezone)).date()


def periods_on(windows: Iterable[Window], day: date, timezone: str) -> list[Period]:
    """The periods of one local day, by start, whatever their mode and the kinds they take."""
    zone = ZoneInfo(timezone)
    found = [
        Period(
            day,
            window.start_minute,
            window.end_minute,
            instant(day, window.start_minute, zone),
            instant(day, window.end_minute, zone),
            window.mode,
            window.capacity,
            window.types,
            window.on_date is not None,
        )
        for window in windows_on(windows, day)
        if applies(window, day, None, any_type=True)
    ]
    return sorted(found, key=lambda period: (period.starts_at, period.ends_at))


def period_at(periods: Iterable[Period], moment: datetime, mode: str | None = None) -> Period | None:
    """The period that holds the instant (its end does not belong to it), of ``mode`` when given."""
    for period in periods:
        if period.starts_at <= moment < period.ends_at and mode in (None, period.mode):
            return period
    return None


def open_minutes(period: Period, blocked: Iterable[tuple[datetime, datetime]] = ()) -> int:
    """The minutes of the period no block takes; blocks may overlap each other."""
    taken = timedelta()
    reached = period.starts_at
    for start, end in sorted(blocked):
        start, end = max(start, reached), min(end, period.ends_at)
        if start < end:
            taken += end - start
            reached = end
    return period.minutes - int(taken.total_seconds() // 60)


def is_full(
    period: Period,
    planned: Sequence[int],
    extra: int,
    *,
    blocked: Iterable[tuple[datetime, datetime]] = (),
) -> bool:
    """Whether a session holding ``planned`` (minutes of each appointment) has no room for ``extra`` more.

    With a capacity the appointments are counted; without one their minutes are added.
    """
    if period.capacity is not None:
        return len(planned) >= period.capacity
    return sum(planned) + extra > open_minutes(period, blocked)


@dataclass(frozen=True)
class Booking:
    """A live appointment as a change of plan sees it; ``key`` identifies it to the caller.

    ``arrived`` is a patient who already arrived and waits. An appointment being attended, and a
    fit-in with a time (it never followed the grid), are not given to ``conflicts``.
    """

    key: Hashable
    mode: str
    starts_at: datetime
    ends_at: datetime
    arrived: bool = False


def conflicts(periods: Sequence[Period], bookings: Iterable[Booking]) -> list[tuple[Booking, str, Period | None]]:
    """The appointments a new plan of their day does not hold as they are: ``(booking, reason, period)``.

    ``period`` is where the appointment goes when the reason is a move (``TO_WALK_IN``,
    ``TO_SESSION``) and the period that refuses it when there is one. An appointment the plan
    holds as it is (a time inside a period of booked time; a session whose period keeps its
    bounds) is left out.
    """
    found: list[tuple[Booking, str, Period | None]] = []
    for booking in bookings:
        period = period_at(periods, booking.starts_at)
        if booking.mode == WALK_IN:
            if period is None:
                found.append((booking, OUTSIDE, None))
            elif period.mode != WALK_IN:
                found.append((booking, TO_BOOKED, period))
            elif (period.starts_at, period.ends_at) != (booking.starts_at, booking.ends_at):
                found.append((booking, ARRIVED if booking.arrived else TO_SESSION, period))
        elif period is None or (period.mode == BOOKED and booking.ends_at > period.ends_at):
            found.append((booking, OUTSIDE, None))
        elif period.mode == WALK_IN:
            found.append((booking, ARRIVED if booking.arrived else TO_WALK_IN, period))
    return found
