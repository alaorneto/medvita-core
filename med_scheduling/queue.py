"""The queue of a walk-in session: who is called next (pure, no database).

A patient gets the next number of the session on arrival. The call order puts the patients with
legal priority (Lei 10.048) first and, among equals, the lower arrival number. Whoever has not
arrived has no number and comes after everyone who has, in the order given.

A number is never used twice in a session: the next one comes after the highest ever given, even
when that appointment was cancelled since.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["call_order", "next_number"]


def call_order(entries: Iterable[Any]) -> list[Any]:
    """The entries in the order they are called; each has ``arrival_number`` and ``is_priority``."""
    entries = list(entries)
    arrived = [entry for entry in entries if entry.arrival_number is not None]
    arrived.sort(key=lambda entry: (not entry.is_priority, entry.arrival_number))
    return arrived + [entry for entry in entries if entry.arrival_number is None]


def next_number(numbers: Iterable[int | None]) -> int:
    """The arrival number after the ones the session already gave."""
    return max((number for number in numbers if number is not None), default=0) + 1
