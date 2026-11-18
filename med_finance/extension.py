"""Registries other apps use to plug into the finance app (docs/extension-points.md of the repository).

``register_charge_origin`` declares an app that creates charges through
``FinanceService.create_charge(origin_app=...)``; the label is shown next to the charge. It is
re-exported by ``service_api`` and called in ``ready()`` of the app that plugs in. An origin
registered again with something else is refused (``ValueError``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_LABEL = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True)
class ChargeOrigin:
    app_label: str
    label: Any


_origins: dict[str, ChargeOrigin] = {}


def register_charge_origin(origin: ChargeOrigin) -> ChargeOrigin:
    if not isinstance(origin, ChargeOrigin) or not _LABEL.fullmatch(origin.app_label or ""):
        raise ValueError(f"Invalid charge origin: {origin!r}.")
    existing = _origins.get(origin.app_label)
    if existing is not None and existing != origin:
        raise ValueError(f"The charge origin {origin.app_label} is already registered.")
    _origins[origin.app_label] = origin
    return origin


def charge_origin(app_label: str) -> ChargeOrigin | None:
    return _origins.get(app_label)


@contextmanager
def isolated_origins() -> Iterator[dict[str, ChargeOrigin]]:
    """Tests only: registrations inside the block are undone afterwards."""
    saved = dict(_origins)
    try:
        yield _origins
    finally:
        _origins.clear()
        _origins.update(saved)
