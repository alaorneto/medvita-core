"""The appointment state machine: every allowed and every refused transition (no database)."""

import pytest

from ... import transitions

ALLOWED = {
    ("confirm", "scheduled"): "confirmed",
    ("check_in", "scheduled"): "arrived",
    ("check_in", "confirmed"): "arrived",
    ("start", "arrived"): "in_progress",
    ("complete", "arrived"): "completed",
    ("complete", "in_progress"): "completed",
    ("mark_no_show", "scheduled"): "no_show",
    ("mark_no_show", "confirmed"): "no_show",
    ("cancel", "scheduled"): "cancelled",
    ("cancel", "confirmed"): "cancelled",
    ("cancel", "arrived"): "cancelled",
    # Without a confirmation; undo_target gives "confirmed" for a confirmed one.
    ("undo_check_in", "arrived"): "scheduled",
}


def test_every_transition(subtests):
    for action in transitions.TRANSITIONS:
        for state in transitions.STATES:
            with subtests.test(action=action, state=state):
                expected = ALLOWED.get((action, state))
                if expected is None:
                    with pytest.raises(transitions.InvalidTransition):
                        transitions.target(action, state)
                else:
                    assert transitions.target(action, state) == expected


def test_final_states_have_no_way_out():
    for state in transitions.FINAL:
        assert transitions.actions_from(state) == ()
    assert transitions.actions_from("scheduled") == ("confirm", "check_in", "mark_no_show", "cancel")
    with pytest.raises(transitions.InvalidTransition):
        transitions.target("reopen", "cancelled")
