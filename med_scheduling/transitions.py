"""The states of an appointment and the only transitions allowed between them (pure, no database).

    scheduled ──confirm──► confirmed ──check_in──► arrived ──start──► in_progress ──complete──► completed
        │  └───────────check_in────────────────────►┘          └────────────complete──────────►┘
        ├── mark_no_show ──► no_show       (from scheduled or confirmed, only after the start)
        └── cancel ──► cancelled           (from scheduled, confirmed or arrived)

    arrived ──undo_check_in──► scheduled or confirmed   (the state before the arrival, for a few minutes)

``completed``, ``no_show`` and ``cancelled`` are final: a wrong state is fixed with a new appointment.
``undo_check_in`` takes back an arrival registered by mistake: it goes back to "confirmada" when the
appointment had been confirmed, to "agendada" otherwise (``undo_target``); the service gives it a
deadline after the arrival.
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
    # The result written here is the one without a confirmation; ``undo_target`` gives the real one.
    "undo_check_in": (frozenset({ARRIVED}), SCHEDULED),
}
# The event each transition publishes (``med_scheduling.appointment_<suffix>``).
EVENT_OF = {
    "confirm": "confirmed",
    "check_in": "arrived",
    "start": "started",
    "complete": "completed",
    "mark_no_show": "no_show",
    "cancel": "cancelled",
    "undo_check_in": "arrival_undone",
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


def undo_target(*, confirmed: bool) -> str:
    """The state an arrival taken back returns to: the one before it."""
    return CONFIRMED if confirmed else SCHEDULED


def actions_from(current: str) -> tuple[str, ...]:
    return tuple(action for action, (allowed, _result) in TRANSITIONS.items() if current in allowed)
