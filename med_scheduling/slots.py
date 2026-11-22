"""Free slots of a schedule: pure functions, no database.

The weekly windows are in the wall clock of the practice's time zone. Each day of the interval
turns its windows into slots of ``slot_minutes``; a slot fits when the appointment duration ends
inside the window. Slots that cross a block, a live appointment or a busy interval of the
professional are removed, and so are slots in the past or beyond the booking horizon.

Daylight saving time: slots are generated on the local clock and converted; a local time that
does not exist (the clock jumps forward) is skipped, and an ambiguous one (the clock goes back)
takes its first occurrence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Window:
    """A weekly window as the algorithm needs it (an AvailabilityRule without the database)."""

    weekday: int
    start_minute: int
    end_minute: int
    valid_from: date
    valid_until: date | None = None
    appointment_type_id: UUID | None = None
    appointment_type_ids: frozenset[UUID] = frozenset()

    @property
    def types(self) -> frozenset[UUID]:
        """The kinds the window takes (the set and the single one together); empty for every kind."""
        if self.appointment_type_id is None:
            return frozenset(self.appointment_type_ids)
        return frozenset(self.appointment_type_ids) | {self.appointment_type_id}


def localize(moment: datetime, zone: ZoneInfo) -> datetime | None:
    """A naive local time as an aware one; ``None`` when that time does not exist in the zone."""
    aware = moment.replace(tzinfo=zone, fold=0)
    round_trip = aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    return aware if round_trip == moment else None


def overlaps(start: datetime, end: datetime, intervals: Iterable[tuple[datetime, datetime]]) -> bool:
    return any(other_start < end and start < other_end for other_start, other_end in intervals)


def applies(window: Window, day: date, appointment_type_id: UUID | None, *, any_type: bool = False) -> bool:
    """Whether the window is valid on ``day`` for the type; ``any_type`` takes the restricted windows too."""
    if window.weekday != day.weekday() or day < window.valid_from:
        return False
    if window.valid_until is not None and day > window.valid_until:
        return False
    types = window.types
    if types and not any_type:
        return appointment_type_id in types
    return True


def candidates(
    windows: Sequence[Window],
    day: date,
    *,
    zone: ZoneInfo,
    slot_minutes: int,
    duration_minutes: int,
    appointment_type_id: UUID | None = None,
    any_type: bool = False,
) -> list[tuple[datetime, Window]]:
    """Aware starts of the slots of one day with the window of each, before removing what is taken."""
    found: list[tuple[datetime, Window]] = []
    midnight = datetime.combine(day, time())
    for window in windows:
        if not applies(window, day, appointment_type_id, any_type=any_type):
            continue
        minute = window.start_minute
        while minute + duration_minutes <= window.end_minute:
            start = localize(midnight + timedelta(minutes=minute), zone)
            if start is not None:
                found.append((start, window))
            minute += slot_minutes
    return found


def candidate_starts(
    windows: Sequence[Window],
    day: date,
    *,
    zone: ZoneInfo,
    slot_minutes: int,
    duration_minutes: int,
    appointment_type_id: UUID | None = None,
    any_type: bool = False,
) -> list[datetime]:
    """Aware starts of the slots of one day, before removing what is taken."""
    return [
        start
        for start, _window in candidates(
            windows,
            day,
            zone=zone,
            slot_minutes=slot_minutes,
            duration_minutes=duration_minutes,
            appointment_type_id=appointment_type_id,
            any_type=any_type,
        )
    ]


def typed_slots(
    *,
    windows: Sequence[Window],
    taken: Iterable[tuple[datetime, datetime]],
    start_date: date,
    end_date: date,
    slot_minutes: int,
    duration_minutes: int,
    timezone: str,
    now: datetime,
    horizon_days: int,
    appointment_type_id: UUID | None = None,
    any_type: bool = False,
) -> list[tuple[datetime, datetime, frozenset[UUID]]]:
    """Free ``(start, end, kinds)`` between two local dates, inclusive, sorted and without repetition.

    ``kinds`` are the kinds the window of the slot takes (empty: every kind). ``taken`` gathers
    blocks, live appointments and busy intervals of the professional. A window restricted to some
    kinds gives slots only to them, unless ``any_type`` asks for the slots of every window (the
    view of a whole day).
    """
    zone = ZoneInfo(timezone)
    busy = sorted(taken)
    horizon_end = now + timedelta(days=horizon_days)
    duration = timedelta(minutes=duration_minutes)
    found: dict[datetime, tuple[datetime, frozenset[UUID]]] = {}
    day = start_date
    while day <= end_date:
        for start, window in candidates(
            windows,
            day,
            zone=zone,
            slot_minutes=slot_minutes,
            duration_minutes=duration_minutes,
            appointment_type_id=appointment_type_id,
            any_type=any_type,
        ):
            end = start + duration
            if start < now or start >= horizon_end or overlaps(start, end, busy):
                continue
            found.setdefault(start.astimezone(UTC), (end.astimezone(UTC), window.types))
        day += timedelta(days=1)
    return [(start, end, kinds) for start, (end, kinds) in sorted(found.items())]


def compute_slots(**arguments: Any) -> list[tuple[datetime, datetime]]:
    """Free ``(start, end)`` pairs: ``typed_slots`` without the kinds of each window."""
    return [(start, end) for start, end, _kinds in typed_slots(**arguments)]


def fits_grid(
    windows: Sequence[Window],
    start: datetime,
    end: datetime,
    *,
    timezone: str,
    appointment_type_id: UUID | None = None,
) -> bool:
    """Whether ``[start, end)`` lies inside one window of the grid on its local day."""
    zone = ZoneInfo(timezone)
    local_start = start.astimezone(zone)
    local_end = end.astimezone(zone)
    if local_end.date() != local_start.date() and not (
        local_end.time() == time() and (local_end.date() - local_start.date()).days == 1
    ):
        return False
    day = local_start.date()
    start_minute = local_start.hour * 60 + local_start.minute
    end_minute = start_minute + int((end - start).total_seconds() // 60)
    return any(
        applies(window, day, appointment_type_id)
        and window.start_minute <= start_minute
        and end_minute <= window.end_minute
        for window in windows
    )


def collide(first: Any, second: Any) -> bool:
    """Whether two weekly windows cover the same minute of some day: weekday, minutes and validity cross."""
    if first.weekday != second.weekday:
        return False
    if first.start_minute >= second.end_minute or second.start_minute >= first.end_minute:
        return False
    first_end = first.valid_until or date.max
    second_end = second.valid_until or date.max
    return first.valid_from <= second_end and second.valid_from <= first_end


def windows_of(rules: Iterable[Any], kinds: Mapping[Any, Iterable[UUID]] | None = None) -> list[Window]:
    """The windows of the rules; ``kinds`` gives, by the id of a rule, the kinds its period lists."""
    kinds = kinds or {}
    return [
        Window(
            rule.weekday,
            rule.start_minute,
            rule.end_minute,
            rule.valid_from,
            rule.valid_until,
            rule.appointment_type_id,
            frozenset(kinds.get(getattr(rule, "pk", None), ())),
        )
        for rule in rules
    ]
