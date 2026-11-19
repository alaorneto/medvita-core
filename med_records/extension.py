"""Registries other apps use to plug into the records app (docs/extension-points.md of the repository).

The functions are re-exported by ``service_api``, the only module other apps may import, and are
called in ``ready()`` of the app that plugs in. Codes are ``<app_label>.<name>`` of the calling app;
a code registered again with something else is refused (``ValueError``); a contribution shows only
while its app is active in the current organization.

- ``register_section_type``: a structured section of an encounter. A new ``version`` of a type lives
  next to the old ones: forms use the latest, stored sections keep the version they were saved with.
- ``register_document_kind``: a kind of clinical document with its default text.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_PLUMBING = (
    "applications.med_records.extension",
    "applications.med_records.service_api",
    "applications.med_records.sections",
    "applications.med_records.documents",
)
FIELD_KINDS = ("text", "long_text", "integer", "decimal", "boolean", "choice", "date", "icd10_list")


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


def _check_code(kind: str, code: object, caller: str | None) -> str:
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError(f"{kind}: code must look like '<app_label>.<name>' (got {code!r}).")
    owner = code.split(".", 1)[0]
    if caller is not None and owner != caller:
        raise ValueError(f"{kind}: {caller} cannot register {code!r}, which belongs to {owner}.")
    return code


@dataclass(frozen=True)
class SectionField:
    """One structured field of a section type. ``choices`` are ``(code, label)`` pairs."""

    name: str
    label: Any
    kind: str
    required: bool = False
    unit: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"SectionField {self.name!r}: unknown kind {self.kind!r}.")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", self.name):
            raise ValueError(f"SectionField name {self.name!r} must be a short snake_case identifier.")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"SectionField {self.name!r}: a choice field needs choices.")


@dataclass(frozen=True)
class SectionType:
    """A structured section of an encounter: its fields, version and whether it takes free text."""

    code: str
    label: Any
    fields: tuple[SectionField, ...] = ()
    version: int = 1
    has_text: bool = True

    def __post_init__(self) -> None:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"SectionType {self.code!r}: duplicated field names.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError(f"SectionType {self.code!r}: version is a positive integer.")
        if not self.fields and not self.has_text:
            raise ValueError(f"SectionType {self.code!r}: a section needs fields or free text.")


@dataclass(frozen=True)
class DocumentKind:
    """A kind of clinical document. ``default_body`` may use {{patient_name}}, {{date}}, {{professional_name}}."""

    code: str
    label: Any
    default_body: Any = ""
    notice: Any = ""


class _VersionedRegistry:
    """Section types by code and version."""

    def __init__(self) -> None:
        self._items: dict[str, dict[int, SectionType]] = {}

    def add(self, item: SectionType, *, caller: str | None) -> SectionType:
        code = _check_code("register_section_type", item.code, caller)
        versions = self._items.setdefault(code, {})
        existing = versions.get(item.version)
        if existing is not None and existing != item:
            raise ValueError(f"register_section_type: {code!r} version {item.version} is already registered.")
        versions[item.version] = item
        return item

    def get(self, code: str, version: int | None = None) -> SectionType | None:
        versions = self._items.get(code) or {}
        if not versions:
            return None
        return versions.get(max(versions) if version is None else version)

    def latest(self) -> tuple[SectionType, ...]:
        return tuple(versions[max(versions)] for _code, versions in sorted(self._items.items()) if versions)

    def snapshot(self) -> dict[str, dict[int, SectionType]]:
        return {code: dict(versions) for code, versions in self._items.items()}

    def restore(self, items: dict[str, dict[int, SectionType]]) -> None:
        self._items = {code: dict(versions) for code, versions in items.items()}


class _Registry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, Any] = {}

    def add(self, code: str, value: Any, *, caller: str | None) -> Any:
        _check_code(self.kind, code, caller)
        existing = self._items.get(code)
        if existing is not None and existing != value:
            raise ValueError(f"{self.kind}: {code!r} is already registered.")
        self._items[code] = value
        return value

    def get(self, code: str) -> Any:
        return self._items.get(code)

    def all(self) -> tuple[Any, ...]:
        return tuple(value for _code, value in sorted(self._items.items()))

    def snapshot(self) -> dict[str, Any]:
        return dict(self._items)

    def restore(self, items: dict[str, Any]) -> None:
        self._items = dict(items)


SECTION_TYPES = _VersionedRegistry()
DOCUMENT_KINDS = _Registry("register_document_kind")
REGISTRIES = (SECTION_TYPES, DOCUMENT_KINDS)


def register_section_type(section_type: SectionType) -> SectionType:
    """Declare a section type (or a new version of one); call it in ``ready()``."""
    if not isinstance(section_type, SectionType):
        raise TypeError("register_section_type takes a SectionType.")
    return SECTION_TYPES.add(section_type, caller=_caller_label())


def register_document_kind(kind: DocumentKind) -> DocumentKind:
    """Declare a kind of clinical document; call it in ``ready()``."""
    if not isinstance(kind, DocumentKind):
        raise TypeError("register_document_kind takes a DocumentKind.")
    return DOCUMENT_KINDS.add(kind.code, kind, caller=_caller_label())


def _active(actor: Any, items: tuple[Any, ...]) -> tuple[Any, ...]:
    from skeleton.service_api.applications import ApplicationService

    service = ApplicationService()
    enabled: dict[str, bool] = {}
    result = []
    for item in items:
        app = item.code.split(".", 1)[0]
        if app not in enabled:
            enabled[app] = service.is_enabled(actor=actor, app_id=app)
        if enabled[app]:
            result.append(item)
    return tuple(result)


def active_section_types(actor: Any) -> tuple[SectionType, ...]:
    """The latest version of each section type of an active app."""
    return _active(actor, SECTION_TYPES.latest())


def active_document_kinds(actor: Any) -> tuple[DocumentKind, ...]:
    return _active(actor, DOCUMENT_KINDS.all())


@contextmanager
def isolated_registries(*, empty: bool = False) -> Iterator[None]:
    """Tests only: changes to the registries inside the block are undone afterwards."""
    saved = [(registry, registry.snapshot()) for registry in REGISTRIES]
    if empty:
        for registry, _items in saved:
            registry.restore({})
    try:
        yield
    finally:
        for registry, items in saved:
            registry.restore(items)
