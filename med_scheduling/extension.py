"""Registry other apps use to add actions to an appointment (docs/extension-points.md of the repository).

``register_appointment_action`` is re-exported by ``service_api`` and called in ``ready()`` of the
app that plugs in ("Atender" from the records app, "Receber" from finance). A code is
``<app_label>.<name>`` of the calling app; registering it again with something else is a
``ValueError``; an action shows only while its app is active in the organization.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_PLUMBING = ("applications.med_scheduling.extension", "applications.med_scheduling.service_api")


@dataclass(frozen=True)
class AppointmentAction:
    """A button on an appointment; ``url_name`` receives ``org`` and ``appointment_id``.

    ``icon`` names the concept whose icon the button shows (#144), as ``PatientSection.icon``.
    """

    code: str
    label: Any
    url_name: str
    statuses: tuple[str, ...]
    order: int = 100
    icon: str = ""


_actions: dict[str, AppointmentAction] = {}


def _caller_label() -> str | None:
    from django.apps import apps

    frame = sys._getframe(2)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if module not in _PLUMBING:
            config = apps.get_containing_app_config(module)
            return config.label if config is not None else None
        frame = frame.f_back
    return None


def register_appointment_action(action: AppointmentAction) -> AppointmentAction:
    if not isinstance(action, AppointmentAction):
        raise TypeError("register_appointment_action takes an AppointmentAction.")
    if not _CODE.fullmatch(action.code):
        raise ValueError(f"appointment action: code must look like '<app_label>.<name>' (got {action.code!r}).")
    caller = _caller_label()
    owner = action.code.split(".", 1)[0]
    if caller is not None and caller != owner:
        raise ValueError(f"appointment action: {caller} cannot register {action.code!r}.")
    existing = _actions.get(action.code)
    if existing is not None and existing != action:
        raise ValueError(f"appointment action: {action.code!r} is already registered.")
    _actions[action.code] = action
    return action


def active_actions(actor: Any, status: str) -> list[AppointmentAction]:
    """Actions of apps active in the organization for an appointment in ``status``, in order."""
    from skeleton.service_api.applications import ApplicationService

    service = ApplicationService()
    enabled: dict[str, bool] = {}
    result = []
    for action in _actions.values():
        if status not in action.statuses:
            continue
        app = action.code.split(".", 1)[0]
        if app not in enabled:
            enabled[app] = service.is_enabled(actor=actor, app_id=app)
        if enabled[app]:
            result.append(action)
    return sorted(result, key=lambda action: (action.order, action.code))


@contextmanager
def isolated_actions() -> Iterator[dict[str, AppointmentAction]]:
    """Tests only: registrations inside the block are undone afterwards."""
    saved = dict(_actions)
    try:
        yield _actions
    finally:
        _actions.clear()
        _actions.update(saved)
