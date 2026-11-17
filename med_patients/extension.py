"""Registries other apps use to plug into the patients app (docs/extension-points.md of the repository).

The functions are re-exported by ``service_api``, the only module other apps may import.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_retention_guards: dict[str, Callable[..., str | None]] = {}


def retention_vetoes(*, actor: Any, patient: Any) -> list[str]:
    """The reasons registered guards give to keep the patient (empty: nothing vetoes)."""
    reasons = []
    for _code, guard in sorted(_retention_guards.items()):
        reason = guard(patient_id=patient.pk)
        if reason:
            reasons.append(str(reason))
    return reasons
