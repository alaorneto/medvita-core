"""Pages of the scheduling app: every read and write goes through SchedulingService (and PatientService).

Hours and the current day are the ones of the practice's clock: every page runs with the practice's
time zone active (``practice_page``), whatever the reader's own. A schedule or appointment the actor
cannot read answers 404; a patient the actor cannot read shows as "Paciente não disponível" with its
code only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from functools import wraps
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone as dj_timezone
from django.utils.http import urlencode
from django.utils.translation import gettext, ngettext
from django.views.decorators.http import require_GET, require_POST

from applications.med_patients.service_api import PatientService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.web.views import tenant_page

from . import forms as scheduling_forms
from .service_api import AvailabilityRuleInput, DayWindowInput, ScheduleTypeInput, SchedulingService
from .transitions import actions_from

TRANSITION_LABELS = {
    "confirm": gettext("Confirmar"),
    "check_in": gettext("Registrar chegada"),
    "start": gettext("Iniciar atendimento"),
    "complete": gettext("Concluir"),
    "mark_no_show": gettext("Marcar falta"),
}
WALK_IN = "walk_in"
# The field of the booking page each refusal of the service is about.
BOOKING_FIELDS = {
    "slot_unavailable": "slot",
    "mode_mismatch": "slot",
    "session_full": "slot",
    "room_unavailable": "slot",
    "type_not_allowed": "appointment_type",
}


def _service() -> SchedulingService:
    return SchedulingService()


def conflict_text(error: Conflict, *, stale: str | None = None) -> str:
    """The message of a conflict; ``stale`` names what changed when it was not an appointment."""
    if error.code == "stale_revision" and stale:
        return stale
    if error.code in ("plan_conflicts", "plan_changed"):
        return str(error.detail)  # The service says which appointments, or which day, hold the change.
    texts = {
        "stale_revision": gettext("A consulta mudou desde que a página abriu. Atualize a página e tente de novo."),
        "slot_unavailable": gettext("O horário não está livre."),
        "type_not_allowed": gettext("Esta agenda não atende este tipo de atendimento neste período ou neste modo."),
        "mode_mismatch": gettext(
            "O período escolhido atende de outro modo: com hora marcada escolha um horário; "
            "na ordem de chegada escolha o período."
        ),
        "session_full": gettext(
            "O período de ordem de chegada está lotado. Para incluir o paciente mesmo assim, marque “Encaixe”."
        ),
        "room_unavailable": gettext("A sala já está ocupada neste horário."),
        "invalid_transition": gettext("Esta mudança não é permitida na situação atual."),
        "patient_inactive": gettext("O paciente não está ativo."),
        "processing_restricted": gettext("O tratamento dos dados deste paciente está restrito."),
        "already_set_up": gettext("A agenda já foi configurada nesta organização."),
        "integrity_conflict": gettext("Já existe um registro com esses dados."),
    }
    return texts.get(error.code, gettext("A operação conflita com o estado atual."))


def _schedule_changed() -> str:
    return gettext("A agenda mudou desde que a página abriu. Confira como ela ficou e salve de novo.")


def _messages_of(error: InvalidInput) -> str:
    return " ".join(text for texts in error.errors.values() for text in texts)


def _revision(request: HttpRequest) -> int:
    try:
        return int(request.POST.get("revision", ""))
    except ValueError:
        return 0


def _key(request: HttpRequest) -> str:
    return (request.POST.get("idempotency_key") or "")[:150] or uuid.uuid4().hex


def _uuid_or_404(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise Http404 from None


def _practice_or_none(request: HttpRequest) -> Any:
    """The practice the actor reads, read once per request (every write to it ends in a redirect)."""
    if not hasattr(request, "_med_scheduling_practice"):
        try:
            practice = _service().practice(actor=request.user)
        except (NotFound, Forbidden):
            practice = None
        request._med_scheduling_practice = practice
    return request._med_scheduling_practice


def practice_page(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """A tenant page on the practice's clock.

    The date filters of the templates and ``localdate()`` follow the active time zone, which the core
    sets to the reader's preference. A practice has one clock, and the hours typed in the forms are
    read on it, so the page activates it; with no practice set up yet the reader's stays.
    """

    @wraps(view)
    def on_practice_clock(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        practice = _practice_or_none(request)
        if practice is None:
            return view(request, *args, **kwargs)
        with dj_timezone.override(ZoneInfo(practice.timezone)):
            return view(request, *args, **kwargs)

    return tenant_page()(on_practice_clock)


def _day_param(request: HttpRequest, name: str = "date") -> date:
    value = request.GET.get(name)
    if not value:
        return dj_timezone.localdate()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise Http404 from None


def _patient_names(request: HttpRequest, patient_ids: list[UUID]) -> dict[UUID, Any]:
    """The patients of a page the actor reads, by id: one read for every 200 of them."""
    ids = tuple(dict.fromkeys(patient_ids))
    found: dict[UUID, Any] = {}
    for first in range(0, len(ids), 200):
        try:
            items = PatientService().summaries(actor=request.user, patient_ids=ids[first : first + 200])
        except (Forbidden, NotFound):
            return {}
        found.update((item.sysid, item) for item in items)
    return found


def _context(request: HttpRequest, organization_id: UUID, section: str, **values: Any) -> dict[str, Any]:
    return {"organization_id": organization_id, "section": section, **values}


def _kind_maps(request: HttpRequest) -> tuple[dict[UUID, str], dict[UUID, str]]:
    """The name and the colour of each kind of appointment, read once per page (inactive kinds keep theirs)."""
    try:
        kinds = _service().appointment_types(actor=request.user, active_only=False)
    except (Forbidden, NotFound):
        return {}, {}
    return {kind.sysid: kind.name for kind in kinds}, {kind.sysid: kind.color for kind in kinds}


def _active_kinds(request: HttpRequest) -> tuple[Any, ...]:
    try:
        return _service().appointment_types(actor=request.user)
    except (Forbidden, NotFound):
        return ()


def _all_kinds(request: HttpRequest) -> tuple[Any, ...]:
    """Every kind of the practice, the inactive ones too: a period may still list one."""
    try:
        return _service().appointment_types(actor=request.user, active_only=False)
    except (Forbidden, NotFound):
        return ()


def _kinds_of(request: HttpRequest, schedule_id: UUID, kinds: tuple[Any, ...]) -> list[dict[str, Any]]:
    """The kinds a schedule takes, by name: the kind, how the schedule takes it and the duration there."""
    by_id = {kind.sysid: kind for kind in kinds}
    taken = _service().schedule_types(actor=request.user, schedule_id=schedule_id)
    return [
        {"kind": by_id[item.appointment_type_id], "taken": item, "minutes": item.duration_minutes}
        for item in taken
        if item.appointment_type_id in by_id
    ]


def _with_patients(
    request: HttpRequest,
    rows: Any,
    zone: ZoneInfo,
    colors: dict[UUID, str] | None = None,
    names: dict[UUID, Any] | None = None,
) -> list[dict[str, Any]]:
    """The items of a list of appointments; a kind without a known colour falls back to the template's gray.

    ``names`` are the patients already read for the page; without them the ones of the rows are read.
    """
    rows = list(rows)
    if names is None:
        names = _patient_names(request, [row.patient_id for row in rows])
    colors = colors or {}
    return [
        {
            "row": row,
            "patient": names.get(row.patient_id),
            "local": row.starts_at.astimezone(zone),
            "color": colors.get(row.appointment_type_id, ""),
        }
        for row in rows
    ]


def _timed(rows: Any) -> list[Any]:
    """The appointments with a time of their own: the walk-in ones are shown in their sessions."""
    return [row for row in rows if row.mode != WALK_IN]


def _span(start: datetime, end: datetime, zone: ZoneInfo) -> str:
    """The hours of a period on the practice's clock; a period that ends at midnight ends at 24:00."""
    first, last = start.astimezone(zone), end.astimezone(zone)
    closing = "24:00" if (last.hour, last.minute) == (0, 0) and last.date() > first.date() else f"{last:%H:%M}"
    return f"{first:%H:%M}–{closing}"


def _occupancy(capacity: int | None, taken: int, planned: int, open_minutes: int) -> str:
    """How much of a walk-in period is taken, in the words every page uses."""
    if capacity is not None:
        return ngettext("%(taken)d de %(capacity)d vaga", "%(taken)d de %(capacity)d vagas", capacity) % {
            "taken": taken,
            "capacity": capacity,
        }
    return ngettext(
        "%(taken)d paciente · %(planned)d de %(open)d min",
        "%(taken)d pacientes · %(planned)d de %(open)d min",
        taken,
    ) % {"taken": taken, "planned": planned, "open": open_minutes}


def _session_cards(
    sessions: Any,
    schedule: Any,
    organization_id: UUID,
    zone: ZoneInfo,
    names: dict[UUID, Any],
    kind_names: dict[UUID, str],
    colors: dict[UUID, str],
) -> list[dict[str, Any]]:
    """The walk-in sessions of a schedule for a page: hours, occupancy and the groups of the queue.

    ``arrive_url`` opens the booking page on the session with the arrival ticked ("Chegou agora"),
    for whoever writes the schedule, while the period of today has not ended.
    """
    today, now = dj_timezone.localdate(), dj_timezone.now()

    def items(entries: Any) -> list[dict[str, Any]]:
        return [
            {
                "entry": entry,
                "row": entry.appointment,
                "patient": names.get(entry.appointment.patient_id),
                "kind": kind_names.get(entry.appointment.appointment_type_id, ""),
                "color": colors.get(entry.appointment.appointment_type_id, ""),
                "arrived": entry.arrived_at.astimezone(zone) if entry.arrived_at else None,
            }
            for entry in entries
        ]

    cards = []
    for session in sessions:
        arrive_url = ""
        if schedule.writable and session.day == today and session.ends_at > now:
            arrive_url = "{}?{}".format(
                reverse("med_scheduling:book", args=(organization_id,)),
                urlencode(
                    {
                        "schedule": schedule.sysid,
                        "day": session.day.isoformat(),
                        "slot": scheduling_forms.BookForm.walk_in_value(session.starts_at),
                        "arrived": "on",
                    }
                ),
            )
        cards.append(
            {
                "session": session,
                "schedule": schedule,
                "id": f"{schedule.sysid.hex}-{session.starts_at.astimezone(zone):%Y%m%d%H%M}",
                "empty": not (session.waiting or session.expected or session.in_progress or session.finished),
                "day": session.day.isoformat(),
                "hours": _span(session.starts_at, session.ends_at, zone),
                "occupancy": _occupancy(session.capacity, session.taken, session.planned_minutes, session.open_minutes),
                "waiting": items(session.waiting),
                "expected": items(session.expected),
                "in_progress": items(session.in_progress),
                "finished": items(session.finished),
                "arrive_url": arrive_url,
            }
        )
    return cards


def _after(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """Where a change of an appointment goes back to: the page that posted it says so (``next``)."""
    target = request.POST.get("next", "")
    if target == "reception":
        return redirect("med_scheduling:reception", organization_id)
    if target == "queue":
        try:
            schedule_id = UUID(request.POST.get("schedule", ""))
            day = date.fromisoformat(request.POST.get("day", ""))
        except ValueError:
            pass
        else:
            return redirect("med_scheduling:queue", organization_id, schedule_id, day.isoformat())
    return redirect("med_scheduling:appointment", organization_id, appointment_id)


def _day_change_url(organization_id: UUID, schedule: Any, day: date) -> str:
    """Where the periods of a day are changed; empty for who does not write the schedule, or for a day that is over."""
    if not schedule.writable or day < dj_timezone.localdate():
        return ""
    return "{}?{}".format(
        reverse("med_scheduling:day-exception", args=(organization_id, schedule.sysid)),
        urlencode({"date": day.isoformat()}),
    )


def _arrival_text(appointment: Any) -> str:
    if appointment.arrival_number is not None:
        return gettext("Chegada registrada: chegada nº %(number)d.") % {"number": appointment.arrival_number}
    return gettext("Chegada registrada.")


# ------------------------------------------------------------------------------------- agenda


@practice_page
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    if _practice_or_none(request) is None:
        return render(request, "med_scheduling/home.html", _context(request, organization_id, "day", practice=None))
    return redirect("med_scheduling:day", organization_id)


@practice_page
def day_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    day = _day_param(request)
    try:
        agendas = _service().day(actor=request.user, date=day)
    except (Forbidden, NotFound):
        agendas = ()
    zone = ZoneInfo(practice.timezone)
    kind_names, colors = _kind_maps(request)
    names = _patient_names(request, [row.patient_id for agenda in agendas for row in agenda.appointments])
    columns = [
        {
            "schedule": agenda.schedule,
            "appointments": _with_patients(request, _timed(agenda.appointments), zone, colors, names),
            "sessions": _session_cards(
                agenda.sessions, agenda.schedule, organization_id, zone, names, kind_names, colors
            ),
            "free": [slot.starts_at.astimezone(zone) for slot in agenda.free],
            "change_url": _day_change_url(organization_id, agenda.schedule, day),
        }
        for agenda in agendas
    ]
    return render(
        request,
        "med_scheduling/day.html",
        _context(
            request,
            organization_id,
            "day",
            day=day,
            previous=day - timedelta(days=1),
            following=day + timedelta(days=1),
            columns=columns,
            practice=practice,
        ),
    )


@practice_page
def week_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    start = _day_param(request, "start")
    start = start - timedelta(days=start.weekday())
    zone = ZoneInfo(practice.timezone)
    kind_names, colors = _kind_maps(request)
    changed = {
        item.date
        for item in _service().day_exceptions(
            actor=request.user, schedule_id=schedule_id, start_date=start, end_date=start + timedelta(days=6)
        )
    }
    rows = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        agendas = _service().day(actor=request.user, date=day, schedule_ids=(schedule.sysid,))
        agenda = agendas[0] if agendas else None
        found = agenda.appointments if agenda else ()
        names = _patient_names(request, [row.patient_id for row in found])
        rows.append(
            {
                "day": day,
                "appointments": _with_patients(request, _timed(found), zone, colors, names),
                "sessions": _session_cards(
                    agenda.sessions if agenda else (), schedule, organization_id, zone, names, kind_names, colors
                ),
                "free": [slot.starts_at.astimezone(zone) for slot in (agenda.free if agenda else ())],
                "changed": day in changed,
                "change_url": _day_change_url(organization_id, schedule, day),
            }
        )
    return render(
        request,
        "med_scheduling/week.html",
        _context(
            request,
            organization_id,
            "day",
            schedule=schedule,
            rows=rows,
            previous=start - timedelta(days=7),
            following=start + timedelta(days=7),
        ),
    )


def _booking_plan(periods: Any, slots: Any, item: dict[str, Any], zone: ZoneInfo, picked: str) -> list[dict[str, Any]]:
    """The periods of a day as the booking page offers them.

    A period of booked time offers its free times; a walk-in period offers itself (``value``, in
    the same group of choices). ``note`` says what keeps the kind out of the period, or what the
    choice takes (a full period only takes a fit-in). ``picked`` is the choice the page came with.
    """
    kind, taken = item["kind"], item["taken"]
    now = dj_timezone.now()
    result = []
    for period in periods:
        walk_in = period.mode == WALK_IN
        listed = not period.appointment_type_ids or kind.sysid in period.appointment_type_ids
        free = [
            {
                "value": slot.starts_at.isoformat(),
                "local": slot.starts_at.astimezone(zone),
                "picked": slot.starts_at.isoformat() == picked,
            }
            for slot in slots
            if not walk_in and period.starts_at <= slot.starts_at < period.ends_at
        ]
        offer, note = walk_in, ""
        if period.ends_at <= now:
            offer, note = False, gettext("Este período já terminou.")
        elif period.open_minutes <= 0:
            offer, note = False, gettext("O período está bloqueado.")
        elif not (taken.allow_walk_in if walk_in else taken.allow_booked):
            offer = False
            text = (
                gettext("A agenda não atende %(kind)s por ordem de chegada.")
                if walk_in
                else gettext("A agenda não atende %(kind)s com hora marcada.")
            )
            note = text % {"kind": kind.name}
        elif not listed:
            note = gettext("Este período não atende %(kind)s: só como encaixe.") % {"kind": kind.name}
        elif walk_in and period.is_full:
            note = gettext("Período lotado. Para incluir o paciente mesmo assim, marque “Encaixe”.")
        elif not walk_in and not free:
            note = gettext("Nenhum horário livre neste período para esta duração.")
        value = scheduling_forms.BookForm.walk_in_value(period.starts_at) if walk_in else ""
        if walk_in:
            occupancy = _occupancy(period.capacity, period.taken, period.planned_minutes, period.open_minutes)
        else:
            occupancy = ngettext("%(count)d consulta marcada", "%(count)d consultas marcadas", period.taken) % {
                "count": period.taken
            }
        result.append(
            {
                "hours": f"{scheduling_forms.clock(period.start_minute)}–{scheduling_forms.clock(period.end_minute)}",
                "mode": period.mode,
                "walk_in": walk_in,
                "full": walk_in and period.is_full,
                "occupancy": occupancy,
                "offer": offer,
                "value": value,
                "picked": bool(value) and value == picked,
                "slots": free,
                "note": note,
            }
        )
    return result


def _asked_slot(values: dict[str, Any], zone: ZoneInfo) -> tuple[datetime | None, str]:
    """The instant and the mode the booking page asked for: a fit-in with a time, a walk-in period or a free time."""
    prefix = scheduling_forms.BookForm.WALK_IN_PREFIX
    if values["fit_in"] and values["fit_in_time"]:
        return datetime.combine(values["day"], values["fit_in_time"], tzinfo=zone), "booked"
    slot, mode = values["slot"], "booked"
    if slot.startswith(prefix):
        slot, mode = slot[len(prefix) :], WALK_IN
    try:
        starts_at = datetime.fromisoformat(slot) if slot else None
    except ValueError:
        starts_at = None
    if starts_at is not None and starts_at.tzinfo is None:
        starts_at = None
    return starts_at, mode


@practice_page
def book_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    if practice is None:
        raise Http404
    query = request.GET.get("q", "")[:200]
    patient_id = request.GET.get("patient") or request.POST.get("patient") or ""
    entry_id = request.GET.get("entry") or request.POST.get("entry") or ""
    patients: tuple[Any, ...] = ()
    patient = None
    if query:
        patients = PatientService().search(actor=request.user, query=query, page_size=20).items
    if patient_id:
        try:
            patient = PatientService().summary(actor=request.user, patient_id=UUID(patient_id))
        except (NotFound, InvalidInput, ValueError):
            raise Http404 from None
    schedules = _service().schedules(actor=request.user)
    data = request.POST or (request.GET if request.GET.get("schedule") else None)
    asked = data if data is not None else request.GET
    # The kinds offered are the ones of the schedule in the form: the one asked for, or the first of the list.
    writable = [item for item in schedules if item.writable]
    schedule = next((item for item in writable if str(item.sysid) == asked.get("schedule")), None)
    schedule = schedule or (writable[0] if writable else None)
    offered = _kinds_of(request, schedule.sysid, _active_kinds(request)) if schedule else []
    wanted = asked.get("appointment_type", "")
    if entry_id and wanted:
        # From the waitlist the kind is the one of the entry.
        offered = [item for item in offered if str(item["kind"].sysid) == wanted]
    first = offered[0] if offered else None
    if asked.get("slot", "").startswith(scheduling_forms.BookForm.WALK_IN_PREFIX):
        # The page came for a walk-in period: the kind suggested is one the schedule takes that way.
        first = next((item for item in offered if item["taken"].allow_walk_in), first)
    selected = next((item for item in offered if str(item["kind"].sysid) == wanted), first)
    suggested = selected["minutes"] if selected else None
    today = dj_timezone.localdate()
    # What the page carries while the patient is searched for: where it came from, never who or why.
    carried = {name: asked.get(name, "")[:80] for name in ("schedule", "day", "slot", "arrived") if asked.get(name)}
    if data is not None:
        data = data.copy()
        # A page opened on a period ("Chegou agora") has the schedule and the day; the kind is the suggested one.
        if not data.get("appointment_type") and selected is not None:
            data["appointment_type"] = str(selected["kind"].sysid)
        if not data.get("day"):
            data["day"] = today.isoformat()
        # A duration nobody typed follows the kind: empty, or still the one the page had suggested.
        typed, before = (data.get(name, "").strip() for name in ("duration", "suggested_duration"))
        if not typed or (request.method != "POST" and typed == before):
            data["duration"] = "" if suggested is None else str(suggested)
        data["suggested_duration"] = "" if suggested is None else str(suggested)
    form = scheduling_forms.BookForm(
        data,
        schedules=schedules,
        type_choices=[
            (
                str(item["kind"].sysid),
                gettext("%(name)s · %(minutes)s min") % {"name": item["kind"].name, "minutes": item["minutes"]},
            )
            for item in offered
        ],
        initial={
            "day": today,
            "appointment_type": wanted,
            "duration": suggested,
            "suggested_duration": suggested,
        },
    )
    # For the optional script: the duration of each kind offered, so it follows the kind as it is picked.
    form.fields["appointment_type"].widget.attrs["data-kind-durations"] = json.dumps(
        {str(item["kind"].sysid): item["minutes"] for item in offered}
    )
    plan: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    status = 200
    zone = ZoneInfo(practice.timezone)
    if data is not None and form.is_valid() and patient is not None:
        values = form.cleaned_data
        schedule_id, type_id = UUID(values["schedule"]), UUID(values["appointment_type"])
        duration = values["duration"] or suggested
        picked = values["slot"]  # Kept apart: a field that gets an error leaves the cleaned values.
        chosen = {
            "kind": selected["kind"],
            "suggested": suggested,
            "minutes": duration,
            "day": values["day"],
            "today": values["day"] == today,
            "schedule_id": schedule_id,
        }
        if request.method == "POST":
            starts_at, mode = _asked_slot(values, zone)
            if starts_at is None:
                form.add_error("slot", gettext("Escolha um horário, ou um período de ordem de chegada."))
                status = 400
            elif values["arrived"] and values["day"] != today:
                form.add_error("arrived", gettext("A chegada só é registrada no dia da consulta."))
                status = 400
            else:
                try:
                    with transaction.atomic():
                        if entry_id:
                            appointment = _service().book_from_waitlist(
                                actor=request.user,
                                entry_id=_uuid_or_404(entry_id),
                                schedule_id=schedule_id,
                                starts_at=starts_at,
                                expected_revision=_revision(request),
                                idempotency_key=_key(request),
                                duration_minutes=duration,
                                mode=mode,
                            )
                        else:
                            appointment = _service().book(
                                actor=request.user,
                                schedule_id=schedule_id,
                                patient_id=patient.sysid,
                                appointment_type_id=type_id,
                                starts_at=starts_at,
                                duration_minutes=duration,
                                fit_in=values["fit_in"],
                                notes=values["notes"],
                                payment_kind=values["payment_kind"] or None,
                                idempotency_key=_key(request),
                                mode=mode,
                                modality=values["modality"] or None,
                            )
                        # A form sent twice finds the appointment as the first one left it.
                        if appointment.status in ("scheduled", "confirmed"):
                            if values["arrived"]:
                                appointment = _service().check_in(
                                    actor=request.user,
                                    appointment_id=appointment.sysid,
                                    expected_revision=appointment.revision,
                                    priority=values["priority"],
                                )
                            elif values["priority"]:
                                appointment = _service().set_priority(
                                    actor=request.user,
                                    appointment_id=appointment.sysid,
                                    priority=True,
                                    expected_revision=appointment.revision,
                                )
                except (Forbidden, NotFound):
                    raise Http404 from None
                except InvalidInput as error:
                    scheduling_forms.apply_service_errors(form, error)
                    status = 400
                except Conflict as error:
                    form.add_error(BOOKING_FIELDS.get(error.code), conflict_text(error))
                    status = 400
                else:
                    if not values["arrived"]:
                        messages.success(request, gettext("Consulta marcada."))
                        return redirect("med_scheduling:appointment", organization_id, appointment.sysid)
                    messages.success(
                        request, gettext("Consulta marcada. %(arrival)s") % {"arrival": _arrival_text(appointment)}
                    )
                    if appointment.mode == WALK_IN:
                        return redirect("med_scheduling:queue", organization_id, schedule_id, values["day"].isoformat())
                    return redirect("med_scheduling:reception", organization_id)
        found = _service().available_slots(
            actor=request.user,
            schedule_id=schedule_id,
            start_date=values["day"],
            end_date=values["day"],
            appointment_type_id=type_id,
            duration_minutes=duration,
        )
        periods = _service().day_plan(
            actor=request.user, schedule_id=schedule_id, start_date=values["day"], end_date=values["day"]
        )
        plan = _booking_plan(periods, found, selected, zone, picked)
    elif request.method == "POST":
        status = 400
    return render(
        request,
        "med_scheduling/book.html",
        _context(
            request,
            organization_id,
            "book",
            query=query,
            patients=patients,
            patient=patient,
            form=form,
            chosen=chosen,
            no_kinds=schedule is not None and not offered,
            plan=plan,
            carried=carried,
            carry=urlencode(carried),
            idempotency_key=_key(request),
            entry_id=entry_id,
            entry_revision=request.GET.get("revision") or request.POST.get("revision") or "",
        ),
        status=status,
    )


@practice_page
def appointment_view(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    try:
        detail = _service().appointment(actor=request.user, appointment_id=appointment_id)
        actions = _service().appointment_actions(actor=request.user, appointment_id=appointment_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    row = detail.appointment
    patient = _patient_names(request, [row.patient_id]).get(row.patient_id)
    zone = ZoneInfo(practice.timezone if practice else "UTC")
    registered = []
    for action in actions:
        try:
            registered.append(
                {"label": action.label, "url": reverse(action.url_name, args=(organization_id, row.sysid))}
            )
        except NoReverseMatch:
            continue
    transitions = [
        {"name": name, "label": TRANSITION_LABELS[name]}
        for name in actions_from(row.status)
        if name in TRANSITION_LABELS
    ]
    walk_in = row.mode == WALK_IN
    return render(
        request,
        "med_scheduling/appointment.html",
        _context(
            request,
            organization_id,
            "day",
            detail=detail,
            row=row,
            patient=patient,
            local_start=row.starts_at.astimezone(zone),
            local_end=row.ends_at.astimezone(zone),
            walk_in=walk_in,
            hours=_span(row.starts_at, row.ends_at, zone),
            queue_day=row.starts_at.astimezone(zone).date().isoformat(),
            transitions=transitions if detail.writable else [],
            registered=registered,
            reschedule_form=scheduling_forms.RescheduleForm(walk_in=walk_in),
            cancel_form=scheduling_forms.CancelForm(),
            can_cancel="cancel" in actions_from(row.status) and detail.writable,
            # Who arrived for a walk-in session keeps the number: the appointment is not moved.
            can_reschedule=detail.writable
            and row.status in (("scheduled", "confirmed") if walk_in else ("scheduled", "confirmed", "arrived")),
            can_set_priority=detail.writable and walk_in and row.status in ("scheduled", "confirmed", "arrived"),
            can_set_modality=detail.writable and row.status in ("scheduled", "confirmed", "arrived"),
            modalities=scheduling_forms.Modality.choices,
        ),
    )


@require_POST
@practice_page
def appointment_check_in(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """Register the arrival, with the legal priority when the page says so (``priority``)."""
    try:
        with transaction.atomic():
            arrived = _service().check_in(
                actor=request.user,
                appointment_id=appointment_id,
                expected_revision=_revision(request),
                priority=request.POST.get("priority") == "on",
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, _arrival_text(arrived))
    return _after(request, organization_id, appointment_id)


@require_POST
@practice_page
def appointment_modality(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """Change where an appointment that has not started is seen (in person or telehealth)."""
    try:
        with transaction.atomic():
            _service().set_modality(
                actor=request.user,
                appointment_id=appointment_id,
                modality=request.POST.get("modality", ""),
                expected_revision=_revision(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, " ".join(text for texts in error.errors.values() for text in texts))
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Modalidade da consulta salva."))
    return _after(request, organization_id, appointment_id)


@require_POST
@practice_page
def appointment_priority(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """Set or take off the legal priority mark of an appointment that has not started."""
    priority = request.POST.get("priority") == "on"
    try:
        with transaction.atomic():
            _service().set_priority(
                actor=request.user,
                appointment_id=appointment_id,
                priority=priority,
                expected_revision=_revision(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(
            request,
            gettext("Atendimento prioritário marcado.") if priority else gettext("Prioridade retirada."),
        )
    return _after(request, organization_id, appointment_id)


@require_POST
@practice_page
def appointment_transition(
    request: HttpRequest, organization_id: UUID, appointment_id: UUID, name: str
) -> HttpResponse:
    if name not in TRANSITION_LABELS:
        raise Http404
    try:
        with transaction.atomic():
            getattr(_service(), name)(
                actor=request.user, appointment_id=appointment_id, expected_revision=_revision(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Situação atualizada."))
    return _after(request, organization_id, appointment_id)


@require_POST
@practice_page
def appointment_reschedule(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    try:
        current = _service().appointment(actor=request.user, appointment_id=appointment_id).appointment
    except (NotFound, Forbidden):
        raise Http404 from None
    form = scheduling_forms.RescheduleForm(request.POST, walk_in=current.mode == WALK_IN)
    if not form.is_valid() or practice is None:
        messages.error(request, gettext("Informe a nova data e hora."))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    starts_at = datetime.combine(
        form.cleaned_data["day"], form.cleaned_data["time"], tzinfo=ZoneInfo(practice.timezone)
    )
    try:
        with transaction.atomic():
            moved = _service().reschedule(
                actor=request.user,
                appointment_id=appointment_id,
                starts_at=starts_at,
                expected_revision=_revision(request),
                mode=form.cleaned_data["mode"] or None,
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    except InvalidInput as error:
        messages.error(request, _messages_of(error))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    messages.success(request, gettext("Consulta remarcada."))
    return redirect("med_scheduling:appointment", organization_id, moved.sysid)


@require_POST
@practice_page
def appointment_cancel(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    form = scheduling_forms.CancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext("Escolha o motivo do cancelamento."))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    try:
        with transaction.atomic():
            _service().cancel(
                actor=request.user,
                appointment_id=appointment_id,
                reason=form.cleaned_data["reason"],
                note=form.cleaned_data["note"],
                expected_revision=_revision(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Consulta cancelada."))
    return redirect("med_scheduling:appointment", organization_id, appointment_id)


@practice_page
def reception_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    today = dj_timezone.localdate()
    agendas = _service().day(actor=request.user, date=today)
    zone = ZoneInfo(practice.timezone)
    kind_names, colors = _kind_maps(request)
    rows = [row for agenda in agendas for row in agenda.appointments]
    names = _patient_names(request, [row.patient_id for row in rows])
    # The appointments with a time go to the three lists; the walk-in ones to the queue of their session.
    items = _with_patients(request, _timed(rows), zone, colors, names)
    schedules = {agenda.schedule.sysid: agenda.schedule for agenda in agendas}
    for item in items:
        item["schedule"] = schedules.get(item["row"].schedule_id)
    queues = [
        card
        for agenda in agendas
        for card in _session_cards(agenda.sessions, agenda.schedule, organization_id, zone, names, kind_names, colors)
    ]
    return render(
        request,
        "med_scheduling/reception.html",
        _context(
            request,
            organization_id,
            "reception",
            today=today,
            waiting=sorted((item for item in items if item["row"].status == "arrived"), key=lambda item: item["local"]),
            in_progress=[item for item in items if item["row"].status == "in_progress"],
            upcoming=[item for item in items if item["row"].status in ("scheduled", "confirmed")],
            queues=queues,
        ),
    )


@practice_page
def queue_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID, day: str) -> HttpResponse:
    """The walk-in sessions of a schedule on one day, each with its queue; who cannot read the schedule gets 404."""
    practice = _practice_or_none(request)
    try:
        when = date.fromisoformat(day)
    except ValueError:
        raise Http404 from None
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
        sessions = _service().queue(actor=request.user, schedule_id=schedule_id, date=when)
    except (NotFound, Forbidden):
        raise Http404 from None
    if practice is None:
        raise Http404
    zone = ZoneInfo(practice.timezone)
    kind_names, colors = _kind_maps(request)
    names = _patient_names(
        request,
        [
            entry.appointment.patient_id
            for session in sessions
            for group in (session.waiting, session.expected, session.in_progress, session.finished)
            for entry in group
        ],
    )
    return render(
        request,
        "med_scheduling/queue.html",
        _context(
            request,
            organization_id,
            "reception",
            schedule=schedule,
            day=when,
            previous=when - timedelta(days=1),
            following=when + timedelta(days=1),
            queues=_session_cards(sessions, schedule, organization_id, zone, names, kind_names, colors),
        ),
    )


@practice_page
def waitlist_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    types = _service().appointment_types(actor=request.user)
    form = scheduling_forms.WaitlistForm(
        request.POST or None, types=types, initial={"earliest_date": dj_timezone.localdate()}
    )
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            found = PatientService().search(actor=request.user, query=values["patient_code"], page_size=2).items
            if len(found) != 1:
                form.add_error("patient_code", gettext("Paciente não encontrado."))
            else:
                try:
                    with transaction.atomic():
                        _service().add_to_waitlist(
                            actor=request.user,
                            patient_id=found[0].sysid,
                            appointment_type_id=UUID(values["appointment_type"])
                            if values["appointment_type"]
                            else None,
                            preferred_period=values["preferred_period"],
                            earliest_date=values["earliest_date"],
                            latest_date=values["latest_date"],
                            priority=values["priority"],
                            note=values["note"],
                            idempotency_key=_key(request),
                        )
                except (NotFound, Forbidden):
                    raise Http404 from None
                except InvalidInput as error:
                    scheduling_forms.apply_service_errors(form, error)
                except Conflict as error:
                    form.add_error(None, conflict_text(error))
                else:
                    messages.success(request, gettext("Paciente incluído na lista de espera."))
                    return redirect("med_scheduling:waitlist", organization_id)
    page = _service().waitlist(actor=request.user)
    names = _patient_names(request, [entry.patient_id for entry in page.items])
    return render(
        request,
        "med_scheduling/waitlist.html",
        _context(
            request,
            organization_id,
            "waitlist",
            entries=[{"entry": entry, "patient": names.get(entry.patient_id)} for entry in page.items],
            form=form,
            practice=practice,
            idempotency_key=_key(request),
        ),
        status=status,
    )


@require_POST
@practice_page
def waitlist_cancel(request: HttpRequest, organization_id: UUID, entry_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().cancel_waitlist_entry(
                actor=request.user, entry_id=entry_id, expected_revision=_revision(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    return redirect("med_scheduling:waitlist", organization_id)


# ------------------------------------------------------------------------------------- settings


@practice_page
def settings_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """Practice data, professionals, rooms and appointment types; writes only with update on the practice."""
    from skeleton.service_api.organizations import OrganizationService

    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    members = OrganizationService().members(actor=request.user, page_size=100).items
    # The professional's own schedule is offered only to who may create one.
    for_professional = {"members": members, "with_schedule": _manages_access(request)}
    practice_initial = {field: getattr(practice, field) for field in scheduling_forms.PracticeForm.base_fields}
    forms = {
        "practice": scheduling_forms.PracticeForm(prefix="practice", initial=practice_initial),
        "professional": scheduling_forms.ProfessionalForm(prefix="professional", **for_professional),
        "room": scheduling_forms.RoomForm(prefix="room"),
        "type": scheduling_forms.TypeForm(prefix="type"),
    }
    status = 200
    if request.method == "POST":
        kind = request.POST.get("form", "")
        if kind not in forms or not practice.writable:
            raise Http404
        extra = for_professional if kind == "professional" else {}
        form = type(forms[kind])(request.POST, prefix=kind, **extra)
        forms[kind] = form
        status = 400
        if form.is_valid():
            values = dict(form.cleaned_data)
            schedule = None
            try:
                with transaction.atomic():
                    if kind == "practice":
                        _service().update_practice(
                            actor=request.user, changes=tuple(values.items()), expected_revision=_revision(request)
                        )
                    elif kind == "professional":
                        member = values.pop("member")
                        with_schedule = values.pop("create_schedule", False)
                        professional = _service().register_professional(
                            actor=request.user,
                            membership_user_id=UUID(member) if member else None,
                            idempotency_key=_key(request),
                            **values,
                        )
                        if with_schedule:
                            # In the same transaction: a schedule that fails takes the professional back.
                            schedule = _service().create_schedule(
                                actor=request.user,
                                name=professional.display_name[:120],
                                professional_id=professional.sysid,
                                idempotency_key=_key(request),
                            )
                    elif kind == "room":
                        _service().add_room(actor=request.user, idempotency_key=_key(request), **values)
                    else:
                        _service().add_appointment_type(actor=request.user, idempotency_key=_key(request), **values)
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                if schedule is not None:
                    messages.success(
                        request, gettext("Profissional cadastrado com a agenda dele. Monte a grade semanal a seguir.")
                    )
                    return redirect("med_scheduling:schedule", organization_id, schedule.sysid)
                messages.success(request, gettext("Configuração salva."))
                return redirect("med_scheduling:settings", organization_id)
    return render(
        request,
        "med_scheduling/settings.html",
        _context(
            request,
            organization_id,
            "settings",
            practice=practice,
            professionals=_service().professionals(actor=request.user, active_only=False),
            rooms=_service().rooms(actor=request.user, active_only=False),
            types=_service().appointment_types(actor=request.user, active_only=False),
            forms=forms,
            idempotency_key=_key(request),
        ),
        status=status,
    )


@practice_page
def type_edit_view(request: HttpRequest, organization_id: UUID, type_id: UUID) -> HttpResponse:
    """Change a kind of appointment; only who updates the practice opens it."""
    practice = _practice_or_none(request)
    if practice is None or not practice.writable:
        raise Http404
    kinds = _service().appointment_types(actor=request.user, active_only=False)
    kind = next((item for item in kinds if item.sysid == type_id), None)
    if kind is None:
        raise Http404
    initial = {name: getattr(kind, name) for name in scheduling_forms.TypeEditForm.base_fields}
    form = scheduling_forms.TypeEditForm(request.POST or None, initial=initial)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    _service().update_appointment_type(
                        actor=request.user,
                        type_id=type_id,
                        changes=tuple(form.cleaned_data.items()),
                        expected_revision=_revision(request),
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(form, error)
            except Conflict as error:
                if error.code == "stale_revision":
                    # The page reopens with what the kind is now, so nobody saves over what they did not see.
                    messages.error(
                        request,
                        gettext(
                            "O tipo de atendimento mudou desde que a página abriu. Confira como ele ficou e salve de novo."
                        ),
                    )
                    return redirect("med_scheduling:type-edit", organization_id, type_id)
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Tipo de atendimento salvo."))
                return redirect("med_scheduling:settings", organization_id)
    return render(
        request,
        "med_scheduling/type_edit.html",
        _context(request, organization_id, "settings", kind=kind, form=form),
        status=status,
    )


def _manages_access(request: HttpRequest) -> bool:
    from skeleton.service_api.access import AccessService

    return "access.manage" in AccessService().capabilities(actor=request.user)


def _core_url(name: str, **kwargs: Any) -> str:
    """A page of the core calendar by its route name; empty when the host does not serve it."""
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return ""


def _organization_address(organization_id: UUID, path: str) -> str:
    """A path the core gives relative to the organization, as an address of this organization."""
    home = reverse("med_scheduling:home", args=(organization_id,))
    own = "apps/med_scheduling/"
    if not home.endswith(own) or path.startswith("/") or "//" in path or ".." in path:
        raise Http404
    return home.removesuffix(own) + path


@require_GET
@practice_page
def calendar_subscribe(request: HttpRequest, organization_id: UUID, calendar_id: UUID) -> HttpResponse:
    """To the page of the core where the person makes their own subscription link to one calendar.

    The app makes no link and sees no token: the core authorizes the calendar, issues the link and
    checks it at each request. Who does not read the calendar (so, the schedule) gets a 404.
    """
    try:
        pages = _service().calendar_pages(actor=request.user, calendar_id=calendar_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    return redirect(_organization_address(organization_id, pages.subscription_path))


def _calendar_section(request: HttpRequest, organization_id: UUID, *, manager: bool = False) -> dict[str, Any]:
    """The calendars the person reads, with the ways out the core calendar has.

    The app makes no link of its own and keeps no token: opening, downloading and subscribing are
    pages of the core, which authorizes each one. ``pending`` counts the calendars of schedules an
    access manager can still mark as managed by this app.
    """
    rows = [
        {
            "entry": entry,
            "subscribe_url": reverse("med_scheduling:calendar-subscribe", args=(organization_id, entry.calendar_id)),
            "schedule_url": (
                reverse("med_scheduling:schedule", args=(organization_id, entry.schedule_id))
                if entry.schedule_id
                else ""
            ),
            "ics_url": _core_url(
                "skeleton_calendar:calendar-ics", organization_id=organization_id, sysid=entry.calendar_id
            ),
        }
        for entry in _service().calendars(actor=request.user)
    ]
    return {
        "schedules": [row for row in rows if row["entry"].schedule_id],
        "others": [row for row in rows if not row["entry"].schedule_id],
        "open_url": _core_url("skeleton_calendar:home", organization_id=organization_id),
        "shared_url": _core_url("skeleton_calendar:calendars", organization_id=organization_id),
        "pending": (
            sum(1 for row in rows if row["entry"].schedule_id and row["entry"].writable and not row["entry"].is_managed)
            if manager
            else 0
        ),
    }


@practice_page
def schedules_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.organizations import OrganizationService

    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    manager = _manages_access(request)
    groups = OrganizationService().groups(actor=request.user, page_size=100).items if manager else ()
    form = scheduling_forms.ScheduleForm(
        request.POST or None,
        professionals=_service().professionals(actor=request.user),
        rooms=_service().rooms(actor=request.user),
        groups=groups,
    )
    status = 200
    if request.method == "POST":
        if not manager:
            raise Http404
        if request.POST.get("form") == "claim":
            try:
                with transaction.atomic():
                    marked = _service().claim_schedule_calendars(actor=request.user)
            except (NotFound, Forbidden):
                raise Http404 from None
            except Conflict as error:
                messages.error(request, conflict_text(error))
            else:
                done = ngettext(
                    "%(count)d calendário foi vinculado à agenda médica.",
                    "%(count)d calendários foram vinculados à agenda médica.",
                    marked,
                ) % {"count": marked}
                nothing = gettext("Os calendários das agendas já estavam vinculados à agenda médica.")
                messages.success(request, done if marked else nothing)
            return redirect("med_scheduling:schedules", organization_id)
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            try:
                with transaction.atomic():
                    created = _service().create_schedule(
                        actor=request.user,
                        name=values["name"],
                        professional_id=UUID(values["professional"]) if values["professional"] else None,
                        room_id=UUID(values["room"]) if values["room"] else None,
                        slot_minutes=values["slot_minutes"],
                        writer_group_ids=tuple(UUID(value) for value in values["writer_groups"]),
                        reader_group_ids=tuple(UUID(value) for value in values["reader_groups"]),
                        idempotency_key=_key(request),
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Agenda criada."))
                return redirect("med_scheduling:schedule", organization_id, created.sysid)
    return render(
        request,
        "med_scheduling/schedules.html",
        _context(
            request,
            organization_id,
            "schedules",
            schedules=_service().schedules(actor=request.user, active_only=False),
            calendars=_calendar_section(request, organization_id, manager=manager),
            form=form,
            manager=manager,
            idempotency_key=_key(request),
        ),
        status=status,
    )


def _kept(rule: Any) -> AvailabilityRuleInput:
    """A period of the grid as it is, so the grid is saved again with it untouched."""
    return AvailabilityRuleInput(
        rule.weekday,
        rule.start_minute,
        rule.end_minute,
        rule.valid_from,
        rule.valid_until,
        None,
        rule.appointment_type_ids,
        rule.mode,
        rule.capacity,
    )


def _typed(period: Any) -> AvailabilityRuleInput:
    """A period a form read (``forms.Period``)."""
    return AvailabilityRuleInput(
        period.weekday,
        period.start_minute,
        period.end_minute,
        period.valid_from,
        period.valid_until,
        None,
        period.kinds,
        period.mode,
        period.capacity,
    )


def _mode_kinds(taken: list[dict[str, Any]]) -> dict[str, set[UUID]]:
    """The kinds a schedule takes in each mode, as the forms of a period name them."""
    return {
        "booked_kinds": {item["kind"].sysid for item in taken if item["taken"].allow_booked},
        "walk_in_kinds": {item["kind"].sysid for item in taken if item["taken"].allow_walk_in},
    }


def _split(rule: Any, period: Any, asked: str) -> tuple[AvailabilityRuleInput, ...]:
    """The period typed over ``rule``; with a day ``asked``, the rule stays as it is until the eve and the typed one holds from it."""
    try:
        day = date.fromisoformat(asked)
    except ValueError:
        return (_typed(period),)
    changed = _typed(replace(period, valid_from=day))
    if rule.valid_from >= day:
        return (changed,)
    return (replace(_kept(rule), valid_until=day - timedelta(days=1)), changed)


def _period_text(period: Any, names: dict[UUID, str]) -> dict[str, Any]:
    """A period for a list: its hours, its mode, its places and the names of the kinds it takes."""
    return {
        "hours": f"{scheduling_forms.clock(period.start_minute)}–{scheduling_forms.clock(period.end_minute)}",
        "mode": period.mode,
        "walk_in": period.mode == WALK_IN,
        "capacity": period.capacity,
        "kinds": [names.get(type_id, gettext("Tipo não disponível")) for type_id in period.appointment_type_ids],
    }


# The field of a period form each key of the service's refusal is about.
PERIOD_FIELDS = {"appointment_type_ids": "kinds"}
# The lines the page of a day offers, at least; a day with more periods gets two beyond them.
DAY_LINES = 4


def _grid_or_404(request: HttpRequest, schedule_id: UUID) -> tuple[Any, tuple[Any, ...]]:
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
        return schedule, _service().availability(actor=request.user, schedule_id=schedule_id)
    except (NotFound, Forbidden):
        raise Http404 from None


def _week(rules: Any, every: tuple[Any, ...], offered: set[UUID], today: date) -> list[dict[str, Any]]:
    """The weekly grid for the page: the seven weekdays, each with its periods and the names of their kinds.

    A period with no kinds takes every kind of the schedule. A kind the schedule no longer takes
    stays listed, marked, until somebody changes the period.
    """
    names = {kind.sysid: kind.name for kind in every}
    days: dict[int, list[dict[str, Any]]] = {weekday: [] for weekday, _label in scheduling_forms.WEEKDAYS}
    for rule in rules:
        days[rule.weekday].append(
            {
                "rule": rule,
                "walk_in": rule.mode == WALK_IN,
                "start": scheduling_forms.clock(rule.start_minute),
                "end": scheduling_forms.clock(rule.end_minute),
                "kinds": [
                    {"name": names.get(type_id, gettext("Tipo não disponível")), "taken": type_id in offered}
                    for type_id in rule.appointment_type_ids
                ],
                "starts": rule.valid_from if rule.valid_from > today else None,
                "until": rule.valid_until,
                "ended": rule.valid_until is not None and rule.valid_until < today,
            }
        )
    return [
        {"number": weekday, "label": label, "periods": days[weekday]} for weekday, label in scheduling_forms.WEEKDAYS
    ]


@practice_page
def schedule_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    schedule, rules = _grid_or_404(request, schedule_id)
    zone = ZoneInfo(practice.timezone)
    today = dj_timezone.localdate()
    every = _all_kinds(request)
    kinds = tuple(kind for kind in every if kind.is_active)
    taken = _kinds_of(request, schedule_id, kinds)
    offered = [item["kind"] for item in taken]
    configured = {item["kind"].sysid: item["taken"] for item in taken if item["taken"].configured}
    types_form_class = scheduling_forms.ScheduleTypesForm
    types_initial: dict[str, Any] = {
        "scope": types_form_class.CHOSEN if configured else types_form_class.ALL,
        **{types_form_class.on(item): item.sysid in configured for item in kinds},
        **{
            types_form_class.booked(item): configured[item.sysid].allow_booked if item.sysid in configured else True
            for item in kinds
        },
        **{
            types_form_class.walk_in(item): configured[item.sysid].allow_walk_in if item.sysid in configured else True
            for item in kinds
        },
        **{
            types_form_class.minutes(item): configured[item.sysid].own_duration
            for item in kinds
            if item.sysid in configured
        },
    }
    page_forms: dict[str, Any] = {
        "periods": scheduling_forms.PeriodsForm(
            initial={"valid_from": today}, prefix="periods", kinds=offered, existing=rules, **_mode_kinds(taken)
        ),
        "types": types_form_class(initial=types_initial, prefix="types", kinds=kinds),
        "block": scheduling_forms.BlockForm(prefix="block"),
    }
    names = {kind.sysid: kind.name for kind in every}
    changed_days = [
        {
            "date": item.date,
            "periods": [_period_text(window, names) for window in item.windows],
            "url": _day_change_url(organization_id, schedule, item.date),
        }
        for item in _service().day_exceptions(actor=request.user, schedule_id=schedule_id)
    ]
    status = 200
    if request.method == "POST":
        if not schedule.writable:
            raise Http404
        kind = request.POST.get("form", "")
        if kind not in page_forms:
            raise Http404
        status = 400
        extra: dict[str, Any] = {}
        if kind == "types":
            extra = {"kinds": kinds}
        elif kind == "periods":
            extra = {"kinds": offered, "existing": rules, **_mode_kinds(taken)}
        target = type(page_forms[kind])(request.POST, prefix=kind, **extra)
        page_forms[kind] = target
        if target.is_valid():
            values = target.cleaned_data
            try:
                with transaction.atomic():
                    if kind == "periods":
                        # The grid as it is plus the periods typed: the ones that stay keep their rows.
                        _service().set_availability(
                            actor=request.user,
                            schedule_id=schedule_id,
                            rules=(*map(_kept, rules), *map(_typed, target.periods)),
                            expected_revision=_revision(request),
                        )
                    elif kind == "types":
                        _service().set_schedule_types(
                            actor=request.user,
                            schedule_id=schedule_id,
                            types=tuple(ScheduleTypeInput(*item) for item in target.chosen()),
                            expected_revision=_revision(request),
                        )
                    else:
                        _service().add_block(
                            actor=request.user,
                            schedule_id=schedule_id,
                            starts_at=datetime.combine(values["day"], values["start"], tzinfo=zone),
                            ends_at=datetime.combine(values["day"], values["end"], tzinfo=zone),
                            reason=values["reason"],
                            note=values["note"],
                            idempotency_key=_key(request),
                        )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(target, error, PERIOD_FIELDS)
            except Conflict as error:
                if kind in ("types", "periods") and error.code == "stale_revision":
                    # The page reopens with the schedule as it is now, so nobody saves over what they did not see.
                    messages.error(request, _schedule_changed())
                    return redirect("med_scheduling:schedule", organization_id, schedule_id)
                target.add_error(None, conflict_text(error, stale=_schedule_changed()))
            else:
                saved = {
                    "periods": gettext("Períodos incluídos na grade semanal."),
                    "types": gettext("Tipos de atendimento da agenda salvos."),
                    "block": gettext("Bloqueio incluído."),
                }
                messages.success(request, saved[kind])
                return redirect("med_scheduling:schedule", organization_id, schedule_id)
    now = dj_timezone.now()
    blocks = _service().blocks(
        actor=request.user, schedule_id=schedule_id, start=now - timedelta(days=1), end=now + timedelta(days=365)
    )
    return render(
        request,
        "med_scheduling/schedule.html",
        _context(
            request,
            organization_id,
            "schedules",
            schedule=schedule,
            week=_week(rules, every, {kind.sysid for kind in offered}, today),
            periods_form=page_forms["periods"],
            types_form=page_forms["types"],
            block_form=page_forms["block"],
            taken=taken,
            every_kind=not configured,
            changed_days=changed_days,
            day_form=scheduling_forms.DayPickForm(initial={"date": today}),
            blocks=[
                {"block": block, "start": block.starts_at.astimezone(zone), "end": block.ends_at.astimezone(zone)}
                for block in blocks
            ],
            idempotency_key=_key(request),
        ),
        status=status,
    )


@practice_page
def period_edit_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID, rule_id: UUID) -> HttpResponse:
    """Change one period of the weekly grid; only who writes the schedule opens it."""
    schedule, rules = _grid_or_404(request, schedule_id)
    rule = next((item for item in rules if item.sysid == rule_id), None)
    if not schedule.writable or rule is None:
        raise Http404
    others = tuple(item for item in rules if item.sysid != rule_id)
    every = _all_kinds(request)
    taken = _kinds_of(request, schedule_id, tuple(k for k in every if k.is_active))
    offered = [item["kind"] for item in taken]
    offered_ids = {kind.sysid for kind in offered}
    names = {kind.sysid: kind.name for kind in every}
    # Kinds the period lists and the schedule no longer takes: they are not offered, so they leave on saving.
    leaving = [
        names.get(type_id, gettext("Tipo não disponível"))
        for type_id in rule.appointment_type_ids
        if type_id not in offered_ids
    ]
    initial = {
        "weekday": rule.weekday,
        "start": time(rule.start_minute // 60, rule.start_minute % 60),
        "end": time((rule.end_minute // 60) % 24, rule.end_minute % 60),
        "mode": rule.mode,
        "capacity": rule.capacity,
        "kinds": [str(type_id) for type_id in rule.appointment_type_ids if type_id in offered_ids],
        "valid_from": rule.valid_from,
        "valid_until": rule.valid_until,
    }
    form = scheduling_forms.PeriodForm(
        request.POST or None, initial=initial, kinds=offered, existing=others, **_mode_kinds(taken)
    )
    status = 200
    split_from: date | None = None
    if request.method == "POST":
        status = 400
        if form.is_valid():
            wanted = _split(rule, form.period, request.POST.get("split_from", ""))
            sent = (*map(_kept, others), *wanted)
            try:
                with transaction.atomic():
                    _service().set_availability(
                        actor=request.user, schedule_id=schedule_id, rules=sent, expected_revision=_revision(request)
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(form, error, PERIOD_FIELDS)
            except Conflict as error:
                if error.code == "stale_revision":
                    # The grid is shown as it is now: the period may have changed, or left it.
                    messages.error(request, _schedule_changed())
                    return redirect("med_scheduling:schedule", organization_id, schedule_id)
                form.add_error(None, conflict_text(error))
                if error.code == "plan_conflicts":
                    # The change may hold from the day after the last appointment it does not fit.
                    held = _service().availability_conflicts(actor=request.user, schedule_id=schedule_id, rules=sent)
                    zone = ZoneInfo(_practice_or_none(request).timezone)
                    days = [item.appointment.starts_at.astimezone(zone).date() for item in held]
                    split_from = max(days) + timedelta(days=1) if days else None
            else:
                messages.success(request, gettext("Período salvo."))
                return redirect("med_scheduling:schedule", organization_id, schedule_id)
    return render(
        request,
        "med_scheduling/period_edit.html",
        _context(
            request,
            organization_id,
            "schedules",
            schedule=schedule,
            form=form,
            leaving=leaving,
            split_from=split_from,
            period={
                "weekday": dict(scheduling_forms.WEEKDAYS)[rule.weekday],
                "start": scheduling_forms.clock(rule.start_minute),
                "end": scheduling_forms.clock(rule.end_minute),
            },
        ),
        status=status,
    )


@require_POST
@practice_page
def period_remove(request: HttpRequest, organization_id: UUID, schedule_id: UUID, rule_id: UUID) -> HttpResponse:
    """Take one period out of the weekly grid; the appointments already booked in it do not change."""
    schedule, rules = _grid_or_404(request, schedule_id)
    if not schedule.writable:
        raise Http404
    kept = tuple(item for item in rules if item.sysid != rule_id)
    if len(kept) == len(rules):
        messages.error(request, gettext("Este período já não está na grade."))
        return redirect("med_scheduling:schedule", organization_id, schedule_id)
    try:
        with transaction.atomic():
            _service().set_availability(
                actor=request.user,
                schedule_id=schedule_id,
                rules=tuple(map(_kept, kept)),
                expected_revision=_revision(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _messages_of(error))
    except Conflict as error:
        messages.error(request, conflict_text(error, stale=_schedule_changed()))
    else:
        messages.success(request, gettext("Período removido da grade semanal."))
    return redirect("med_scheduling:schedule", organization_id, schedule_id)


def _day_initial(periods: Any, modes: dict[str, set[UUID]], to_walk_in: bool) -> dict[str, Any]:
    """The lines of the day form filled with the periods the day follows; ``to_walk_in`` turns them all walk-in."""
    initial: dict[str, Any] = {}
    for line, period in enumerate(periods, start=1):
        mode = WALK_IN if to_walk_in else period.mode
        taken = modes["walk_in_kinds" if mode == WALK_IN else "booked_kinds"]
        initial.update(
            {
                f"start_{line}": time(period.start_minute // 60, period.start_minute % 60),
                f"end_{line}": time((period.end_minute // 60) % 24, period.end_minute % 60),
                f"mode_{line}": mode,
                f"capacity_{line}": period.capacity,
                f"kinds_{line}": [str(type_id) for type_id in period.appointment_type_ids if type_id in taken],
            }
        )
    return initial


def _plan_effect(item: Any, zone: ZoneInfo) -> str:
    """What a change of the periods of a day does to one appointment, in the words of the confirmation."""
    hours = _span(item.starts_at, item.ends_at, zone) if item.starts_at and item.ends_at else ""
    texts = {
        "to_walk_in": gettext("Passa para a ordem de chegada das %(hours)s."),
        "to_session": gettext("Continua na ordem de chegada, no período que passa a ser %(hours)s."),
        "to_booked": gettext("É de ordem de chegada, e o período passaria a ter hora marcada."),
        "outside": gettext("Fica fora dos períodos do dia."),
        "arrived": gettext("O paciente já chegou: o período dele não muda mais."),
    }
    return texts.get(item.reason, gettext("A mudança não comporta esta consulta.")) % {"hours": hours}


def _plan_review(request: HttpRequest, schedule_id: UUID, day: date, windows: Any, zone: ZoneInfo) -> dict[str, Any]:
    """The appointments a change of the periods of a day moves, and the ones that refuse it, for the confirmation."""
    found = _service().plan_conflicts(actor=request.user, schedule_id=schedule_id, date=day, windows=windows)
    names = _patient_names(request, [item.appointment.patient_id for item in found])
    items = [
        {
            "row": item.appointment,
            "patient": names.get(item.appointment.patient_id),
            "local": item.appointment.starts_at.astimezone(zone),
            "hours": _span(item.appointment.starts_at, item.appointment.ends_at, zone),
            "effect": _plan_effect(item, zone),
            "blocking": item.blocking,
            "over_capacity": item.over_capacity,
            "kind_not_listed": item.kind_not_listed,
        }
        for item in found
    ]
    return {
        "moves": [item for item in items if not item["blocking"]],
        "blocking": [item for item in items if item["blocking"]],
    }


@practice_page
def day_exception_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID) -> HttpResponse:
    """Change the periods of one day of a schedule, or take the day back to the weekly grid.

    A change that moves appointments already booked is shown first (which ones, and which refuse
    it) and is made only when confirmed with that list. Only who writes the schedule opens the page.
    """
    practice = _practice_or_none(request)
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    if practice is None or not schedule.writable:
        raise Http404
    day = _day_param(request)
    zone = ZoneInfo(practice.timezone)
    past = day < dj_timezone.localdate()
    here = "{}?{}".format(request.path, urlencode({"date": day.isoformat()}))
    try:
        periods = _service().day_plan(actor=request.user, schedule_id=schedule_id, start_date=day, end_date=day)
    except (NotFound, Forbidden):
        raise Http404 from None
    every = _all_kinds(request)
    taken = _kinds_of(request, schedule_id, tuple(kind for kind in every if kind.is_active))
    modes = _mode_kinds(taken)
    options: dict[str, Any] = {
        "lines": max(DAY_LINES, len(periods) + 2),
        "kinds": [item["kind"] for item in taken],
        **modes,
    }
    prefilled = request.method == "GET" and request.GET.get("mode") == WALK_IN
    form = scheduling_forms.DayForm(initial=_day_initial(periods, modes, prefilled), **options)
    review: dict[str, Any] | None = None
    action, carried, status = "", [], 200
    if request.method == "POST":
        action = request.POST.get("form", "")
        if past or action not in ("change", "clear"):
            raise Http404
        confirmed = request.POST.get("step") == "confirm"
        seen = tuple(_uuid_or_404(value) for value in request.POST.getlist("affected"))
        windows: tuple[DayWindowInput, ...] | None = None
        status = 400
        if action == "change":
            form = scheduling_forms.DayForm(request.POST, **options)
            if form.is_valid():
                windows = tuple(
                    DayWindowInput(item.start_minute, item.end_minute, item.mode, item.capacity, item.kinds)
                    for item in form.periods
                )
        if action == "clear" or windows is not None:
            call: dict[str, Any] = {
                "actor": request.user,
                "schedule_id": schedule_id,
                "date": day,
                "expected_revision": _revision(request),
                "convert_existing": confirmed,
                "expected_affected": seen if confirmed else None,
            }
            try:
                with transaction.atomic():
                    if action == "change":
                        _service().set_day_exception(windows=windows, **call)
                    else:
                        _service().clear_day_exception(**call)
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                if action == "clear":
                    messages.error(request, _messages_of(error))
                    return redirect(here)
                scheduling_forms.apply_service_errors(form, error)
            except Conflict as error:
                if error.code == "stale_revision":
                    # The day is shown as it is now, so nobody saves over what they did not see.
                    messages.error(request, _schedule_changed())
                    return redirect(here)
                if error.code not in ("plan_conflicts", "plan_changed"):
                    messages.error(request, conflict_text(error))
                    return redirect(here)
                review = _plan_review(request, schedule_id, day, windows, zone)
                if not (review["moves"] or review["blocking"]):
                    # What held the change is gone meanwhile: the same form goes through now.
                    messages.error(request, gettext("As consultas deste dia mudaram. Salve de novo."))
                    review = None
                else:
                    review["again"] = confirmed
                    status = 400 if review["blocking"] else 200
                    # The periods typed go along with the confirmation, as they were sent.
                    carried = [
                        (name, value) for name in form.fields for value in request.POST.getlist(name) if value != ""
                    ]
            else:
                if action == "clear":
                    messages.success(request, gettext("O dia voltou a seguir a grade semanal."))
                else:
                    messages.success(request, gettext("Períodos do dia salvos."))
                if confirmed and seen:
                    messages.info(
                        request,
                        ngettext(
                            "%(count)d consulta passou para a ordem de chegada do período.",
                            "%(count)d consultas passaram para a ordem de chegada do período.",
                            len(seen),
                        )
                        % {"count": len(seen)},
                    )
                return redirect(
                    "{}?{}".format(reverse("med_scheduling:day", args=(organization_id,)), urlencode({"date": day}))
                )
    names = {kind.sysid: kind.name for kind in every}
    current = [
        {
            **_period_text(period, names),
            "taken": period.taken,
            "occupancy": _occupancy(period.capacity, period.taken, period.planned_minutes, period.open_minutes),
        }
        for period in periods
    ]
    walk_in_url = ""
    if request.method == "GET" and not past and not prefilled and any(period.mode != WALK_IN for period in periods):
        walk_in_url = f"{here}&{urlencode({'mode': WALK_IN})}"
    return render(
        request,
        "med_scheduling/day_exception.html",
        _context(
            request,
            organization_id,
            "schedules",
            schedule=schedule,
            day=day,
            past=past,
            changed=any(period.is_exception for period in periods),
            current=current,
            form=form,
            lines=form.lines(),
            prefilled=prefilled,
            walk_in_url=walk_in_url,
            here=here,
            review=review,
            action=action,
            carried=carried,
        ),
        status=status,
    )


@require_POST
@practice_page
def block_remove(request: HttpRequest, organization_id: UUID, schedule_id: UUID, block_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().remove_block(actor=request.user, block_id=block_id, expected_revision=_revision(request))
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    return redirect("med_scheduling:schedule", organization_id, schedule_id)


@practice_page
def setup_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService
    from skeleton.service_api.organizations import OrganizationService

    if "access.manage" not in AccessService().capabilities(actor=request.user):
        raise Http404
    groups = OrganizationService().groups(actor=request.user, page_size=100).items
    form = scheduling_forms.SetupForm(
        request.POST or None, groups=groups, initial={"practice_name": gettext("Consultório")}
    )
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            try:
                with transaction.atomic():
                    _service().setup(
                        actor=request.user,
                        practice_name=values["practice_name"],
                        timezone=values["timezone"],
                        reader_group_ids=tuple(UUID(value) for value in values["reader_groups"]),
                        manager_group_ids=tuple(UUID(value) for value in values["manager_groups"]),
                        idempotency_key=f"page-setup-{organization_id}",
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                scheduling_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Agenda configurada."))
                return redirect("med_scheduling:settings", organization_id)
    return render(
        request, "med_scheduling/setup.html", _context(request, organization_id, "settings", form=form), status=status
    )


# ------------------------------------------------------------------------------- patient page


@practice_page
def patient_section(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    """The "Consultas" tab of the patient page."""
    practice = _practice_or_none(request)
    try:
        patient = PatientService().summary(actor=request.user, patient_id=patient_id)
        tabs = PatientService().page_tabs(actor=request.user, patient_id=patient_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    navigation = []
    for tab in tabs:
        try:
            url = reverse(tab.url_name, args=(organization_id, patient_id))
        except NoReverseMatch:
            continue
        navigation.append({"label": tab.label, "url": url, "current": tab.code == "med_scheduling.appointments"})
    try:
        rows = list(_service().appointments(actor=request.user, patient_id=patient_id, page_size=100).items)
    except (Forbidden, NotFound):
        rows = []
    zone = ZoneInfo(practice.timezone if practice else "UTC")
    rows.sort(key=lambda row: row.starts_at, reverse=True)
    return render(
        request,
        "med_scheduling/patient_section.html",
        _context(
            request,
            organization_id,
            "day",
            patient=patient,
            tabs=navigation,
            rows=[
                {
                    "row": row,
                    "local": row.starts_at.astimezone(zone),
                    "walk_in": row.mode == WALK_IN,
                    "hours": _span(row.starts_at, row.ends_at, zone),
                }
                for row in rows
            ],
        ),
    )
