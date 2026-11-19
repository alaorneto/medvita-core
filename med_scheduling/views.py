"""Pages of the scheduling app: every read and write goes through SchedulingService (and PatientService).

Hours are shown on the practice's clock. A schedule or appointment the actor cannot read answers
404; a patient the actor cannot read shows as "Paciente não disponível" with its code only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from applications.med_patients.service_api import PatientService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.web.views import tenant_page

from . import forms as scheduling_forms
from .service_api import AvailabilityRuleInput, SchedulingService
from .transitions import actions_from

TRANSITION_LABELS = {
    "confirm": gettext("Confirmar"),
    "check_in": gettext("Registrar chegada"),
    "start": gettext("Iniciar atendimento"),
    "complete": gettext("Concluir"),
    "mark_no_show": gettext("Marcar falta"),
}


def _service() -> SchedulingService:
    return SchedulingService()


def conflict_text(error: Conflict) -> str:
    texts = {
        "stale_revision": gettext("A consulta mudou desde que a página abriu. Atualize a página e tente de novo."),
        "slot_unavailable": gettext("O horário não está livre."),
        "room_unavailable": gettext("A sala já está ocupada neste horário."),
        "invalid_transition": gettext("Esta mudança não é permitida na situação atual."),
        "patient_inactive": gettext("O paciente não está ativo."),
        "processing_restricted": gettext("O tratamento dos dados deste paciente está restrito."),
        "already_set_up": gettext("A agenda já foi configurada nesta organização."),
        "integrity_conflict": gettext("Já existe um registro com esses dados."),
    }
    return texts.get(error.code, gettext("A operação conflita com o estado atual."))


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
    try:
        return _service().practice(actor=request.user)
    except (NotFound, Forbidden):
        return None


def _day_param(request: HttpRequest, name: str = "date") -> date:
    value = request.GET.get(name)
    if not value:
        return dj_timezone.localdate()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise Http404 from None


def _patient_names(request: HttpRequest, patient_ids: list[UUID]) -> dict[UUID, Any]:
    if not patient_ids:
        return {}
    try:
        found = PatientService().summaries(actor=request.user, patient_ids=tuple(dict.fromkeys(patient_ids))[:200])
    except (Forbidden, NotFound):
        return {}
    return {item.sysid: item for item in found}


def _context(request: HttpRequest, organization_id: UUID, section: str, **values: Any) -> dict[str, Any]:
    return {"organization_id": organization_id, "section": section, **values}


def _with_patients(request: HttpRequest, rows: Any, zone: ZoneInfo) -> list[dict[str, Any]]:
    rows = list(rows)
    names = _patient_names(request, [row.patient_id for row in rows])
    return [{"row": row, "patient": names.get(row.patient_id), "local": row.starts_at.astimezone(zone)} for row in rows]


# ------------------------------------------------------------------------------------- agenda


@tenant_page()
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    if _practice_or_none(request) is None:
        return render(request, "med_scheduling/home.html", _context(request, organization_id, "day", practice=None))
    return redirect("med_scheduling:day", organization_id)


@tenant_page()
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
    columns = [
        {
            "schedule": agenda.schedule,
            "appointments": _with_patients(request, agenda.appointments, zone),
            "free": [slot.starts_at.astimezone(zone) for slot in agenda.free],
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


@tenant_page()
def week_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    start = _day_param(request, "start")
    start = start - timedelta(days=start.weekday())
    zone = ZoneInfo(practice.timezone)
    rows = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        agendas = _service().day(actor=request.user, date=day, schedule_ids=(schedule.sysid,))
        agenda = agendas[0] if agendas else None
        rows.append(
            {
                "day": day,
                "appointments": _with_patients(request, agenda.appointments if agenda else (), zone),
                "free": [slot.starts_at.astimezone(zone) for slot in (agenda.free if agenda else ())],
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


@tenant_page()
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
    types = _service().appointment_types(actor=request.user)
    data = request.POST or (request.GET if request.GET.get("schedule") else None)
    form = scheduling_forms.BookForm(data, schedules=schedules, types=types, initial={"day": dj_timezone.localdate()})
    slots: list[datetime] = []
    status = 200
    zone = ZoneInfo(practice.timezone)
    if data is not None and form.is_valid() and patient is not None:
        values = form.cleaned_data
        schedule_id, type_id = UUID(values["schedule"]), UUID(values["appointment_type"])
        if request.method == "POST":
            starts_at: datetime | None = None
            if values["fit_in"] and values["fit_in_time"]:
                starts_at = datetime.combine(values["day"], values["fit_in_time"], tzinfo=zone)
            elif values["slot"]:
                try:
                    starts_at = datetime.fromisoformat(values["slot"])
                except ValueError:
                    starts_at = None
            if starts_at is None:
                form.add_error(None, gettext("Escolha um horário."))
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
                            )
                        else:
                            appointment = _service().book(
                                actor=request.user,
                                schedule_id=schedule_id,
                                patient_id=patient.sysid,
                                appointment_type_id=type_id,
                                starts_at=starts_at,
                                fit_in=values["fit_in"],
                                notes=values["notes"],
                                payment_kind=values["payment_kind"] or "private",
                                idempotency_key=_key(request),
                            )
                except (Forbidden, NotFound):
                    raise Http404 from None
                except InvalidInput as error:
                    scheduling_forms.apply_service_errors(form, error)
                    status = 400
                except Conflict as error:
                    form.add_error(None, conflict_text(error))
                    status = 400
                else:
                    messages.success(request, gettext("Consulta marcada."))
                    return redirect("med_scheduling:appointment", organization_id, appointment.sysid)
        found = _service().available_slots(
            actor=request.user,
            schedule_id=schedule_id,
            start_date=values["day"],
            end_date=values["day"],
            appointment_type_id=type_id,
        )
        slots = [slot.starts_at for slot in found]
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
            slots=[{"value": slot.isoformat(), "local": slot.astimezone(zone)} for slot in slots],
            idempotency_key=_key(request),
            entry_id=entry_id,
            entry_revision=request.GET.get("revision") or request.POST.get("revision") or "",
        ),
        status=status,
    )


@tenant_page()
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
            transitions=transitions if detail.writable else [],
            registered=registered,
            reschedule_form=scheduling_forms.RescheduleForm(),
            cancel_form=scheduling_forms.CancelForm(),
            can_cancel="cancel" in actions_from(row.status) and detail.writable,
            can_reschedule=row.status in ("scheduled", "confirmed", "arrived") and detail.writable,
        ),
    )


@require_POST
@tenant_page()
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
    if request.POST.get("next") == "reception":
        return redirect("med_scheduling:reception", organization_id)
    return redirect("med_scheduling:appointment", organization_id, appointment_id)


@require_POST
@tenant_page()
def appointment_reschedule(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    form = scheduling_forms.RescheduleForm(request.POST)
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
@tenant_page()
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


@tenant_page()
def reception_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    today = dj_timezone.localdate()
    agendas = _service().day(actor=request.user, date=today)
    zone = ZoneInfo(practice.timezone)
    rows = [row for agenda in agendas for row in agenda.appointments]
    items = _with_patients(request, rows, zone)
    schedules = {agenda.schedule.sysid: agenda.schedule for agenda in agendas}
    for item in items:
        item["schedule"] = schedules.get(item["row"].schedule_id)
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
        ),
    )


@tenant_page()
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
@tenant_page()
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


@tenant_page()
def settings_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """Practice data, professionals, rooms and appointment types; writes only with update on the practice."""
    from skeleton.service_api.organizations import OrganizationService

    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    members = OrganizationService().members(actor=request.user, page_size=100).items
    practice_initial = {field: getattr(practice, field) for field in scheduling_forms.PracticeForm.base_fields}
    forms = {
        "practice": scheduling_forms.PracticeForm(prefix="practice", initial=practice_initial),
        "professional": scheduling_forms.ProfessionalForm(prefix="professional", members=members),
        "room": scheduling_forms.RoomForm(prefix="room"),
        "type": scheduling_forms.TypeForm(prefix="type"),
    }
    status = 200
    if request.method == "POST":
        kind = request.POST.get("form", "")
        if kind not in forms or not practice.writable:
            raise Http404
        extra = {"members": members} if kind == "professional" else {}
        form = type(forms[kind])(request.POST, prefix=kind, **extra)
        forms[kind] = form
        status = 400
        if form.is_valid():
            values = dict(form.cleaned_data)
            try:
                with transaction.atomic():
                    if kind == "practice":
                        _service().update_practice(
                            actor=request.user, changes=tuple(values.items()), expected_revision=_revision(request)
                        )
                    elif kind == "professional":
                        member = values.pop("member")
                        _service().register_professional(
                            actor=request.user,
                            membership_user_id=UUID(member) if member else None,
                            idempotency_key=_key(request),
                            **values,
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


@tenant_page()
def schedules_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService
    from skeleton.service_api.organizations import OrganizationService

    practice = _practice_or_none(request)
    if practice is None:
        return redirect("med_scheduling:home", organization_id)
    manager = "access.manage" in AccessService().capabilities(actor=request.user)
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
            form=form,
            manager=manager,
            idempotency_key=_key(request),
        ),
        status=status,
    )


def _grid_rules(form: Any) -> tuple[AvailabilityRuleInput, ...]:
    rules = []
    for weekday, _label in scheduling_forms.WEEKDAYS:
        for slot in (1, 2):
            start = form.cleaned_data.get(f"d{weekday}_{slot}_start")
            end = form.cleaned_data.get(f"d{weekday}_{slot}_end")
            if start and end:
                rules.append(
                    AvailabilityRuleInput(
                        weekday=weekday,
                        start_minute=start.hour * 60 + start.minute,
                        end_minute=end.hour * 60 + end.minute if end != time(0) else 1440,
                        valid_from=form.cleaned_data["valid_from"],
                    )
                )
    return tuple(rules)


@tenant_page()
def schedule_view(request: HttpRequest, organization_id: UUID, schedule_id: UUID) -> HttpResponse:
    practice = _practice_or_none(request)
    try:
        schedule = _service().schedule(actor=request.user, schedule_id=schedule_id)
        rules = _service().availability(actor=request.user, schedule_id=schedule_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    zone = ZoneInfo(practice.timezone)
    initial: dict[str, Any] = {"valid_from": dj_timezone.localdate()}
    counters: dict[int, int] = {}
    for rule in rules:
        slot = counters.get(rule.weekday, 0) + 1
        counters[rule.weekday] = slot
        if slot <= 2:
            initial[f"d{rule.weekday}_{slot}_start"] = time(rule.start_minute // 60, rule.start_minute % 60)
            initial[f"d{rule.weekday}_{slot}_end"] = time((rule.end_minute // 60) % 24, rule.end_minute % 60)
        initial["valid_from"] = rule.valid_from
    grid_form = scheduling_forms.AvailabilityForm(initial=initial, prefix="grid")
    block_form = scheduling_forms.BlockForm(prefix="block")
    status = 200
    if request.method == "POST":
        if not schedule.writable:
            raise Http404
        kind = request.POST.get("form")
        if kind not in ("grid", "block"):
            raise Http404
        status = 400
        target = scheduling_forms.AvailabilityForm(request.POST, prefix="grid") if kind == "grid" else None
        if kind == "block":
            target = scheduling_forms.BlockForm(request.POST, prefix="block")
            block_form = target
        else:
            grid_form = target
        if target.is_valid():
            values = target.cleaned_data
            try:
                with transaction.atomic():
                    if kind == "grid":
                        _service().set_availability(
                            actor=request.user,
                            schedule_id=schedule_id,
                            rules=_grid_rules(target),
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
                scheduling_forms.apply_service_errors(target, error)
            except Conflict as error:
                target.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Grade salva.") if kind == "grid" else gettext("Bloqueio incluído."))
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
            grid_form=grid_form,
            block_form=block_form,
            blocks=[
                {"block": block, "start": block.starts_at.astimezone(zone), "end": block.ends_at.astimezone(zone)}
                for block in blocks
            ],
            idempotency_key=_key(request),
        ),
        status=status,
    )


@require_POST
@tenant_page()
def block_remove(request: HttpRequest, organization_id: UUID, schedule_id: UUID, block_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().remove_block(actor=request.user, block_id=block_id, expected_revision=_revision(request))
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    return redirect("med_scheduling:schedule", organization_id, schedule_id)


@tenant_page()
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


@tenant_page()
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
            rows=[{"row": row, "local": row.starts_at.astimezone(zone)} for row in rows],
        ),
    )
