"""The states of an appointment and the only transitions allowed between them (pure, no database).

    scheduled ──confirm──► confirmed ──check_in──► arrived ──start──► in_progress ──complete──► completed
        │  └───────────check_in────────────────────►┘          └────────────complete──────────►┘
        ├── mark_no_show ──► no_show       (from scheduled or confirmed, only after the start)
        └── cancel ──► cancelled           (from scheduled, confirmed or arrived)

``completed``, ``no_show`` and ``cancelled`` are final: a wrong state is fixed with a new appointment.
"""

from __future__ import annotations

SCHEDULED = "scheduled"
CONFIRMED = "confirmed"
ARRIVED = "arrived"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
NO_SHOW = "no_show"
CANCELLED = "cancelled"

STATES = (SCHEDULED, CONFIRMED, ARRIVED, IN_PROGRESS, COMPLETED, NO_SHOW, CANCELLED)
FINAL = frozenset({COMPLETED, NO_SHOW, CANCELLED})
LIVE = frozenset({SCHEDULED, CONFIRMED, ARRIVED, IN_PROGRESS})

TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "confirm": (frozenset({SCHEDULED}), CONFIRMED),
    "check_in": (frozenset({SCHEDULED, CONFIRMED}), ARRIVED),
    "start": (frozenset({ARRIVED}), IN_PROGRESS),
    "complete": (frozenset({ARRIVED, IN_PROGRESS}), COMPLETED),
    "mark_no_show": (frozenset({SCHEDULED, CONFIRMED}), NO_SHOW),
    "cancel": (frozenset({SCHEDULED, CONFIRMED, ARRIVED}), CANCELLED),
}
# The event each transition publishes (``med_scheduling.appointment_<suffix>``).
EVENT_OF = {
    "confirm": "confirmed",
    "check_in": "arrived",
    "start": "started",
    "complete": "completed",
    "mark_no_show": "no_show",
    "cancel": "cancelled",
}
# The timestamp field each transition fills.
STAMP_OF = {
    "confirm": "confirmed_at",
    "check_in": "arrived_at",
    "start": "started_at",
    "complete": "completed_at",
    "cancel": "cancelled_at",
}


class InvalidTransition(ValueError):
    pass


def target(action: str, current: str) -> str:
    """The state ``action`` leads to from ``current``; ``InvalidTransition`` when not allowed."""
    try:
        allowed, result = TRANSITIONS[action]
    except KeyError:
        raise InvalidTransition(action) from None
    if current not in allowed:
        raise InvalidTransition(f"{action} from {current}")
    return result


def actions_from(current: str) -> tuple[str, ...]:
    return tuple(action for action, (allowed, _result) in TRANSITIONS.items() if current in allowed)
