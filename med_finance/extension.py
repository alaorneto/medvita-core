"""Registries other apps use to plug into the finance app (docs/extension-points.md of the repository).

The functions are re-exported by ``service_api``, the only module other apps may import, and are
called in ``ready()`` of the app that plugs in.

- ``register_charge_origin`` declares an app that creates charges through
  ``FinanceService.create_charge(origin_app=...)``; the label is shown next to the charge. An
  origin registered again with something else is refused (``ValueError``).
- ``register_charge_panel`` and ``register_receipt_panel`` add a panel to the charge and to the
  receipt page (the situation of a fiscal document, of a payout). Codes are ``<app_label>.<name>``
  of the calling app; a code registered again with something else is refused (``ValueError``); a
  panel shows only while its app is active in the organization, to who reads the cash desk.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_LABEL = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_PLUMBING = ("applications.med_finance.extension", "applications.med_finance.service_api")


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


@dataclass(frozen=True)
class _Panel:
    code: str
    label: Any  # Lazy gettext text.
    template: str = ""
    url_name: str = ""
    order: int = 100
    visible: Callable[..., bool] | None = None
    context: Callable[..., Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        if bool(self.template) == bool(self.url_name):
            raise ValueError(f"{type(self).__name__} {self.code!r}: give a template or a url_name, not both.")
        if type(self.order) is not int:
            raise ValueError(f"{type(self).__name__} {self.code!r}: order is an integer.")
        for name in ("visible", "context"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise ValueError(f"{type(self).__name__} {self.code!r}: {name} is a callable.")


@dataclass(frozen=True)
class ChargePanel(_Panel):
    """A panel on the charge page, after the app's own content.

    ``template`` is rendered in the page with ``panel``, ``organization_id``, ``charge_id`` and what
    ``context(actor=..., charge_id=...)`` returns; ``url_name``, instead, is a link to a page of the
    app that receives ``org`` and ``charge_id``. ``visible(actor=..., charge_id=...)``, when given,
    hides the panel; a failure of either hides it too. The panel gets the ``sysid`` only: what it
    shows comes from the service of the app that owns it.
    """


@dataclass(frozen=True)
class ReceiptPanel(_Panel):
    """A panel on the receipt page, like ``ChargePanel`` with ``receipt_id`` in place of ``charge_id``."""


class _Registry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, Any] = {}

    def add(self, code: object, value: Any, *, caller: str | None) -> Any:
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

    def active(self, actor: Any) -> tuple[Any, ...]:
        """The contributions of apps active in the organization, in order."""
        from skeleton.service_api.applications import ApplicationService

        service = ApplicationService()
        enabled: dict[str, bool] = {}
        result = []
        for code, value in sorted(self._items.items()):
            app = code.split(".", 1)[0]
            if app not in enabled:
                enabled[app] = service.is_enabled(actor=actor, app_id=app)
            if enabled[app]:
                result.append(value)
        return tuple(sorted(result, key=lambda item: (item.order, item.code)))

    def snapshot(self) -> dict[str, Any]:
        return dict(self._items)

    def restore(self, items: dict[str, Any]) -> None:
        self._items = dict(items)


CHARGE_PANELS = _Registry("charge panel")
RECEIPT_PANELS = _Registry("receipt panel")


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


def register_charge_panel(panel: ChargePanel) -> ChargePanel:
    """Add a panel to the charge page; call it in ``ready()``."""
    if not isinstance(panel, ChargePanel):
        raise TypeError("register_charge_panel takes a ChargePanel.")
    return CHARGE_PANELS.add(panel.code, panel, caller=_caller_label())


def register_receipt_panel(panel: ReceiptPanel) -> ReceiptPanel:
    """Add a panel to the receipt page; call it in ``ready()``."""
    if not isinstance(panel, ReceiptPanel):
        raise TypeError("register_receipt_panel takes a ReceiptPanel.")
    return RECEIPT_PANELS.add(panel.code, panel, caller=_caller_label())


def call_safely(code: str, function: Callable[..., Any], **arguments: Any) -> tuple[bool, Any]:
    """Run a contribution; a failure is logged (by code and error type only) and reported as ``(False, None)``."""
    try:
        return True, function(**arguments)
    except Exception as exc:  # noqa: BLE001 - one app's failure never breaks the finance page
        logger.warning("med_finance.contribution_failed", extra={"contribution": code, "error": type(exc).__name__})
        return False, None


@contextmanager
def isolated_origins() -> Iterator[dict[str, ChargeOrigin]]:
    """Tests only: registrations inside the block are undone afterwards."""
    saved = dict(_origins)
    try:
        yield _origins
    finally:
        _origins.clear()
        _origins.update(saved)


@contextmanager
def isolated_panels() -> Iterator[None]:
    """Tests only: panels registered inside the block are undone afterwards."""
    saved = [(registry, registry.snapshot()) for registry in (CHARGE_PANELS, RECEIPT_PANELS)]
    try:
        yield
    finally:
        for registry, items in saved:
            registry.restore(items)
