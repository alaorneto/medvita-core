"""Registries other apps use to plug into the patients app (docs/extension-points.md of the repository).

The functions are re-exported by ``service_api``, the only module other apps may import, and are
called in ``ready()`` of the app that plugs in. Every registry:

- accepts only codes ``<app_label>.<name>`` whose app label is the calling app;
- refuses (``ValueError``) a code registered again with something else;
- shows a contribution only while its app is active in the current organization.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class PatientSection:
    """A tab or shortcut on the patient page; ``url_name`` receives ``org`` and ``patient_id``.

    The tabs go by use (#136): Resumo is 0 and the app's own tabs are 50 (Cadastro) to 55
    (Privacidade); an ``order`` below 50 puts the section before Cadastro (the suite uses 20, 30
    and 40), one above 55 after Privacidade.

    ``visible(actor=..., patient_id=...)``, when given, hides the tab from who would only find an
    empty page (a clinical tab for the reception, for example); a failure hides it too.

    ``icon`` names the concept whose icon the tab shows (#144): one of the suite
    (``med_icons.MED_CONCEPT_ICONS``) or of the core (``"privacy"|concept_icon``); empty, no icon.
    """

    code: str
    label: Any
    url_name: str
    order: int = 100
    visible: Callable[..., bool] | None = None
    icon: str = ""


@dataclass(frozen=True)
class SummaryPanel:
    """A panel of the "Resumo" tab, the first one of the patient page (#136).

    ``template`` is rendered in the page with ``panel``, ``organization_id``, ``patient_id`` and what
    ``context(actor=..., patient_id=...)`` returns (a mapping of names to values, read by the
    app's own service with the actor's access). ``visible(actor=..., patient_id=...)``, when given,
    hides the panel from who would read nothing in it (the allergies from the reception, for
    example); a failure of either, or of the template, hides the panel too.
    """

    code: str
    label: Any  # Lazy gettext text.
    template: str
    order: int = 100
    visible: Callable[..., bool] | None = None
    context: Callable[..., Mapping[str, Any]] | None = None
    icon: str = ""  # The concept whose icon the panel title shows (#144), as PatientSection.icon.

    def __post_init__(self) -> None:
        if not isinstance(self.template, str) or not self.template.endswith(".html"):
            raise ValueError(f"SummaryPanel {self.code!r}: template is the name of an .html template.")
        if type(self.order) is not int:
            raise ValueError(f"SummaryPanel {self.code!r}: order is an integer.")
        for name in ("visible", "context"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise ValueError(f"SummaryPanel {self.code!r}: {name} is a callable.")


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One item of the patient timeline. ``title`` never carries health data ("Consulta realizada")."""

    at: datetime
    source: str
    kind: str
    title: str
    url_name: str = ""
    url_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class SetupStep:
    """A step of the clinic setup list; ``is_done(actor=...)`` says whether it is complete."""

    code: str
    label: Any
    url_name: str
    is_done: Callable[..., bool]
    order: int = 100


CONSENT_PURPOSES = Registry("consent purpose")
RETENTION_GUARDS = Registry("retention guard")
PATIENT_SECTIONS = Registry("patient section")
TIMELINE_PROVIDERS = Registry("timeline provider")
DATA_PROVIDERS = Registry("patient data provider")
SETUP_STEPS = Registry("setup step")
PORTAL_PATIENTS = Registry("portal patients resolver")
SUMMARY_PANELS = Registry("summary panel")
REGISTRIES = [
    CONSENT_PURPOSES,
    RETENTION_GUARDS,
    PATIENT_SECTIONS,
    TIMELINE_PROVIDERS,
    DATA_PROVIDERS,
    SETUP_STEPS,
    PORTAL_PATIENTS,
    SUMMARY_PANELS,
]


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


def register_patient_section(section: PatientSection) -> PatientSection:
    """Add a tab or shortcut to the patient page."""
    if not isinstance(section, PatientSection):
        raise TypeError("register_patient_section takes a PatientSection.")
    return PATIENT_SECTIONS.add(section.code, section, caller=_caller_label())


def register_summary_panel(panel: SummaryPanel) -> SummaryPanel:
    """Add a panel to the "Resumo" tab of the patient page."""
    if not isinstance(panel, SummaryPanel):
        raise TypeError("register_summary_panel takes a SummaryPanel.")
    return SUMMARY_PANELS.add(panel.code, panel, caller=_caller_label())


def register_timeline_provider(code: str, provider: Callable[..., tuple[TimelineEntry, ...]]) -> Callable[..., Any]:
    """Add items to the patient timeline.

    ``provider(*, actor, patient_id, before, limit)`` returns at most ``limit`` entries with
    ``at <= before`` (``before`` is ``None`` on the first page), newest first. It authorizes with
    its own service and returns ``()`` when the actor reads nothing.
    """
    if not callable(provider):
        raise TypeError("register_timeline_provider takes a callable.")
    return TIMELINE_PROVIDERS.add(code, provider, caller=_caller_label())


def register_patient_data_provider(
    code: str, provider: Callable[..., tuple[tuple[str, str], ...]]
) -> Callable[..., Any]:
    """Add a section to the data subject report: ``provider(*, actor, patient_id)`` returns (label, value) pairs."""
    if not callable(provider):
        raise TypeError("register_patient_data_provider takes a callable.")
    return DATA_PROVIDERS.add(code, provider, caller=_caller_label())


def register_setup_step(step: SetupStep) -> SetupStep:
    """Add a step to the clinic setup list."""
    if not isinstance(step, SetupStep):
        raise TypeError("register_setup_step takes a SetupStep.")
    return SETUP_STEPS.add(step.code, step, caller=_caller_label())


def register_portal_patients(code: str, resolver: Callable[..., Any]) -> Callable[..., Any]:
    """Say for which patients an external person of the portal acts (the portal app's link).

    ``resolver(*, actor, access_id)`` runs inside the portal (``external_context``) and returns the
    ``sysid`` of the patients the person may act for (the patient, a child): only the ones the app
    linked to that access. Only the resolvers of the app that admitted the person
    (``ExternalAccessInfo.app_label``) are asked. It reads with its own app's service, marked
    ``allow_external``, so a disabled app answers nothing.
    """
    if not callable(resolver):
        raise TypeError("register_portal_patients takes a callable.")
    return PORTAL_PATIENTS.add(code, resolver, caller=_caller_label())


def call_safely(code: str, function: Callable[..., Any], **arguments: Any) -> tuple[bool, Any]:
    """Run a contribution; a failure is logged (by code and error type only) and reported as ``(False, None)``."""
    try:
        return True, function(**arguments)
    except Exception as exc:  # noqa: BLE001 - one app's failure never breaks the patient page
        logger.warning("med_patients.contribution_failed", extra={"contribution": code, "error": type(exc).__name__})
        return False, None


def _app_enabled(actor: Any, code: str) -> bool:
    from skeleton.service_api.applications import ApplicationService

    return ApplicationService().is_enabled(actor=actor, app_id=code.split(".", 1)[0])


# Names the summary page gives every panel template: a panel context never overrides them.
RESERVED_PANEL_NAMES = frozenset({"panel", "organization_id", "patient_id", "request", "csrf_token"})


def summary_panel_context(*, actor: Any, patient_id: Any, code: str) -> dict[str, Any] | None:
    """What the panel ``code`` of the "Resumo" tab shows for the actor and the patient (#136).

    Call it only for a panel ``PatientService().summary_panels`` returned (it authorized the
    patient and applied ``visible``). The panel's ``context`` reads with its own app's service and
    the actor's access. ``None`` when the panel is gone, its app is not active, or its ``context`` fails or is not a
    mapping of names (logged by code and error type only): the page then leaves the panel out.
    """
    panel = dict(SUMMARY_PANELS.all()).get(code)
    if panel is None or not _app_enabled(actor, code):
        return None
    if panel.context is None:
        return {}
    ok, values = call_safely(code, panel.context, actor=actor, patient_id=patient_id)
    if not ok:
        return None
    if not isinstance(values, Mapping) or not all(
        isinstance(name, str) and name.isidentifier() and name not in RESERVED_PANEL_NAMES for name in values
    ):
        logger.warning("med_patients.contribution_failed", extra={"contribution": code, "error": "context"})
        return None
    return dict(values)


def retention_vetoes(*, actor: Any, patient: Any) -> list[str]:
    """The reasons the guards of active apps give to keep the patient (empty: nothing vetoes).

    A guard that fails vetoes too: keeping a patient by mistake is reversible, erasing it is not.
    """
    from django.utils.translation import gettext

    reasons = []
    for code, guard in RETENTION_GUARDS.active(actor):
        ok, reason = call_safely(code, guard, patient_id=patient.pk)
        if not ok:
            reasons.append(gettext("Não foi possível confirmar a retenção ({code}).").format(code=code))
        elif reason:
            reasons.append(str(reason))
    return reasons


@contextmanager
def isolated_registries(*, empty: bool = False) -> Iterator[None]:
    """Tests only: changes to the registries inside the block are undone afterwards.

    With ``empty=True`` the block starts without the contributions the installed apps registered.
    """
    saved = [(registry, registry.snapshot()) for registry in REGISTRIES]
    if empty:
        for registry, _items in saved:
            registry.restore({})
    try:
        yield
    finally:
        for registry, items in saved:
            registry.restore(items)
