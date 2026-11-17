"""Registries other apps use to plug into the patients app (docs/extension-points.md of the repository).

The functions are re-exported by ``service_api``, the only module other apps may import, and are
called in ``ready()`` of the app that plugs in. Every registry:

- accepts only codes ``<app_label>.<name>`` whose app label is the calling app;
- refuses (``ValueError``) a code registered again with something else;
- shows a contribution only while its app is active in the current organization.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
# Frames of this app's own plumbing: the caller is the first frame outside them.
_PLUMBING = ("applications.med_patients.extension", "applications.med_patients.service_api")


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


class Registry:
    """Contributions of the apps, by code; read back only for the apps active in the organization."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, Any] = {}

    def add(self, code: str, value: Any, *, caller: str | None) -> Any:
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError(f"{self.kind}: code must look like '<app_label>.<name>' (got {code!r}).")
        owner = code.split(".", 1)[0]
        if caller is not None and owner != caller:
            raise ValueError(f"{self.kind}: {caller} cannot register {code!r}, which belongs to {owner}.")
        existing = self._items.get(code)
        if existing is not None and existing != value:
            raise ValueError(f"{self.kind}: {code!r} is already registered.")
        self._items[code] = value
        return value

    def all(self) -> tuple[tuple[str, Any], ...]:
        return tuple(sorted(self._items.items()))

    def active(self, actor: Any) -> tuple[tuple[str, Any], ...]:
        """The contributions of apps active in the organization (the actor's context)."""
        from skeleton.service_api.applications import ApplicationService

        service = ApplicationService()
        enabled: dict[str, bool] = {}
        result = []
        for code, value in self.all():
            app = code.split(".", 1)[0]
            if app not in enabled:
                enabled[app] = service.is_enabled(actor=actor, app_id=app)
            if enabled[app]:
                result.append((code, value))
        return tuple(result)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._items)

    def restore(self, items: dict[str, Any]) -> None:
        self._items = dict(items)


@dataclass(frozen=True)
class ConsentPurpose:
    """A purpose of data processing a patient may consent to (beyond care itself)."""

    code: str
    label: Any  # Lazy gettext text.
    description: Any = ""


CONSENT_PURPOSES = Registry("consent purpose")
RETENTION_GUARDS = Registry("retention guard")
REGISTRIES = [CONSENT_PURPOSES, RETENTION_GUARDS]


def register_consent_purpose(purpose: ConsentPurpose) -> ConsentPurpose:
    """Declare a consent purpose; call it in ``ready()`` of the app that uses the consent."""
    if not isinstance(purpose, ConsentPurpose):
        raise TypeError("register_consent_purpose takes a ConsentPurpose.")
    return CONSENT_PURPOSES.add(purpose.code, purpose, caller=_caller_label())


def register_retention_guard(code: str, guard: Callable[..., str | None]) -> Callable[..., str | None]:
    """Declare a guard that may veto deleting or anonymizing a patient.

    ``guard(patient_id=...)`` returns the reason to keep the patient (shown to the administrator)
    or ``None``. It runs inside the caller's organization context and must not open another one.
    """
    if not callable(guard):
        raise TypeError("register_retention_guard takes a callable.")
    return RETENTION_GUARDS.add(code, guard, caller=_caller_label())


def retention_vetoes(*, actor: Any, patient: Any) -> list[str]:
    """The reasons the guards of active apps give to keep the patient (empty: nothing vetoes)."""
    reasons = []
    for _code, guard in RETENTION_GUARDS.active(actor):
        reason = guard(patient_id=patient.pk)
        if reason:
            reasons.append(str(reason))
    return reasons


@contextmanager
def isolated_registries() -> Iterator[None]:
    """Tests only: changes to the registries inside the block are undone afterwards."""
    saved = [(registry, registry.snapshot()) for registry in REGISTRIES]
    try:
        yield
    finally:
        for registry, items in saved:
            registry.restore(items)
