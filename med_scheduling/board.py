"""The day as a board of hours (#135): where each item of a schedule sits on the time axis (pure, no database).

The board is a CSS grid whose rows are steps of the day, from the hour of the first period (or
appointment) to the hour after the last end, shared by every schedule of the page so their
columns line up. An item takes the rows of its start and its length: ``row`` is the first grid
line inside the column of items (1 is the first step) and ``span`` how many steps it covers.
The page places them by class (``r-<row>``, ``s-<span>``), never by ``style=``.

The step is the longest of 15, 10 and 5 minutes that every bound of the day falls on, so a
schedule of 10 or 20 minutes lines up as well as one of 15; a day with bounds off those steps,
or too long for the rows the stylesheet offers, takes 15 minutes or more and rounds (the start
down, the end up). Items whose rows cross get side-by-side lanes (an overlap is a fit-in, or an
appointment over a block), at most ``MAX_LANES``; a band (the background of a period) spans all.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = ["DAY_MINUTES", "MAX_LANES", "MAX_ROWS", "STEPS", "Axis", "axis_of", "lanes"]

DAY_MINUTES = 24 * 60
# The steps a day can take, the longest first; the stylesheet has the classes of MAX_ROWS rows.
STEPS = (15, 10, 5)
COARSE_STEPS = (15, 30, 60)
MAX_ROWS = 96
MAX_LANES = 3


@dataclass(frozen=True, slots=True)
class Axis:
    """The rows of a board: from ``first`` to ``last`` (minutes of the day, on the hour) by ``step`` minutes."""

    first: int
    last: int
    step: int

    @property
    def rows(self) -> int:
        return (self.last - self.first) // self.step

    def place(self, start: int, end: int) -> tuple[int, int] | None:
        """The first row and the number of rows of an item from ``start`` to ``end``; ``None`` outside the axis.

        The start rounds down and the end up, so an item off the step still covers its minutes;
        an item shorter than a step takes one row.
        """
        start, end = max(start, self.first), min(end, self.last)
        if end <= start:
            return None
        row = (start - self.first) // self.step + 1
        last = -(-(end - self.first) // self.step)  # The row of the end, rounded up.
        return row, max(1, last - row + 1)

    def hours(self) -> list[tuple[str, int, int]]:
        """The labels of the axis: each whole hour, its first row and the rows to the next one."""
        per_hour = 60 // self.step if self.step <= 60 else 1
        labels = []
        for minute in range(self.first, self.last, 60):
            row = (minute - self.first) // self.step + 1
            labels.append((f"{minute // 60:02d}:00", row, min(per_hour, self.rows - row + 1)))
        return labels


def axis_of(spans: Iterable[tuple[int, int]]) -> Axis | None:
    """The axis that holds every span (minutes of the day, clipped to it); ``None`` for a day with none."""
    kept = [(max(0, start), min(DAY_MINUTES, end)) for start, end in spans]
    kept = [(start, end) for start, end in kept if end > start]
    if not kept:
        return None
    first = min(start for start, _end in kept) // 60 * 60
    last = min(DAY_MINUTES, -(-max(end for _start, end in kept) // 60) * 60)
    bounds = {minute for span in kept for minute in span}
    for step in STEPS:
        if (last - first) // step <= MAX_ROWS and all((minute - first) % step == 0 for minute in bounds):
            return Axis(first, last, step)
    step = next(step for step in COARSE_STEPS if (last - first) // step <= MAX_ROWS)
    return Axis(first, last, step)


def lanes(rows: Sequence[tuple[int, int]]) -> tuple[list[int], int]:
    """The lane of each item (1 first) by its ``(row, span)``, and how many lanes the column needs.

    Each item takes the first lane free at its row, in the order of the rows; past ``MAX_LANES``
    the item shares the last lane.
    """
    order = sorted(range(len(rows)), key=lambda index: (rows[index][0], -rows[index][1], index))
    ends: list[int] = []  # The row after the last item of each lane.
    found = [1] * len(rows)
    for index in order:
        row, span = rows[index]
        lane = next((number for number, end in enumerate(ends) if end <= row), None)
        if lane is None:
            if len(ends) < MAX_LANES:
                ends.append(0)
                lane = len(ends) - 1
            else:
                lane = MAX_LANES - 1
        ends[lane] = max(ends[lane], row + span)
        found[index] = lane + 1
    return found, max(1, len(ends))
