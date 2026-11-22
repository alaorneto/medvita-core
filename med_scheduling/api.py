"""REST API of the scheduling app, under ``/api/v1/o/<org>/apps/med_scheduling/``.

Every call goes through SchedulingService. Lists never carry the reception's notes; only the
detail of one appointment does. Changes require ``If-Match`` with the current revision; booking
accepts ``Idempotency-Key``. Errors come back as the core's standard responses.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils.translation import gettext
from rest_framework.response import Response

from skeleton.api.openapi import BOOLEAN, INTEGER, Operation, obj, results, string
from skeleton.api.openapi import UUID as UUID_SCHEMA
from skeleton.api.views import request_fields
from skeleton.service_api import InvalidInput

from .api_support import SCOPE_READ, SCOPE_WRITE, ScopedAPI, cursor_page, dto_schema
from .service_api import AppointmentDetail, AppointmentInfo, ScheduleInfo, SchedulingService, Slot

PAGE_SIZE = 50

TRANSITIONS = {
    "confirm": "confirm",
    "check-in": "check_in",
    "start": "start",
    "complete": "complete",
    "no-show": "mark_no_show",
}


def _service() -> SchedulingService:
    return SchedulingService()


def _json(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _if_match(request: Any) -> int:
    header = request.headers.get("If-Match", "").strip().removeprefix("W/")
    try:
        return int(header.strip('"'))
    except ValueError:
        raise InvalidInput({"If-Match": [gettext("Envie a revisão atual no cabeçalho If-Match.")]}) from None


def _with_etag(response: Response, revision: int) -> Response:
    response["ETag"] = f'"{revision}"'
    return response


def _uuid(value: Any, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError:
        raise InvalidInput({field: [gettext("Identificador inválido.")]}) from None


def _datetime(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise InvalidInput({field: [gettext("Informe a data e hora.")]})
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        raise InvalidInput({field: [gettext("Use data e hora ISO 8601 com fuso.")]}) from None
    if parsed.tzinfo is None:
        raise InvalidInput({field: [gettext("Use data e hora ISO 8601 com fuso.")]})
    return parsed


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InvalidInput({field: [gettext("Use uma data válida (AAAA-MM-DD).")]}) from None


def _fields(request: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    fields = request_fields(request)
    unknown = sorted(set(fields) - set(allowed))
    if unknown:
        raise InvalidInput({name: [gettext("Campo não aceito.")] for name in unknown})
    return fields


def _page_size(request: Any) -> int:
    size = request.query_params.get("page_size", "")
    return int(size) if size.isdigit() else PAGE_SIZE


class SchedulesAPI(ScopedAPI):
    token_methods = ("GET",)
    token_scopes = {"GET": SCOPE_READ}
    openapi = {"GET": Operation("Agendas ativas", lambda: results(dto_schema(ScheduleInfo)), scope=SCOPE_READ)}

    def get(self, request, organization_id):
        rows = _service().schedules(actor=request.user)
        return Response({"results": _json(rows)})


class SlotsAPI(ScopedAPI):
    token_methods = ("GET",)
    token_scopes = {"GET": SCOPE_READ}
    openapi = {
        "GET": Operation(
            "Horários livres da agenda",
            lambda: results(dto_schema(Slot)),
            query=(
                ("start", string(format="date"), "Primeiro dia (AAAA-MM-DD)"),
                ("end", string(format="date"), "Último dia; padrão: o primeiro"),
                ("type", UUID_SCHEMA, "Tipo de atendimento"),
            ),
            scope=SCOPE_READ,
        )
    }

    def get(self, request, organization_id, schedule_id):
        params = request.query_params
        start = _date(params.get("start", ""), "start")
        end = _date(params.get("end") or params.get("start", ""), "end")
        slots = _service().available_slots(
            actor=request.user,
            schedule_id=schedule_id,
            start_date=start,
            end_date=end,
            appointment_type_id=_uuid(params.get("type"), "type"),
        )
        return Response({"results": _json(slots)})


BOOK_FIELDS = (
    "schedule",
    "patient",
    "appointment_type",
    "starts_at",
    "duration_minutes",
    "fit_in",
    "notes",
    "payment_kind",
    "room",
)


BOOK_INPUT = obj(
    {
        "schedule": UUID_SCHEMA,
        "patient": UUID_SCHEMA,
        "appointment_type": UUID_SCHEMA,
        "starts_at": string(format="date-time"),
        "duration_minutes": INTEGER,
        "fit_in": BOOLEAN,
        "notes": string(),
        "payment_kind": string(),
        "room": UUID_SCHEMA,
    },
    required=("schedule", "patient", "appointment_type", "starts_at"),
)
APPOINTMENT_QUERY = (
    ("schedule", UUID_SCHEMA, "Agenda"),
    ("patient", UUID_SCHEMA, "Paciente"),
    ("start", string(format="date-time"), "Início do intervalo (ISO 8601 com fuso)"),
    ("end", string(format="date-time"), "Fim do intervalo (ISO 8601 com fuso)"),
    ("status", string(), "Situação"),
    ("cursor", string(), "Cursor devolvido pela página anterior"),
    ("page_size", INTEGER, "Tamanho da página"),
)


class AppointmentsAPI(ScopedAPI):
    token_methods = ("GET", "POST")
    token_scopes = {"GET": SCOPE_READ, "POST": SCOPE_WRITE}
    openapi = {
        "GET": Operation(
            "Consultas", lambda: cursor_page(dto_schema(AppointmentInfo)), query=APPOINTMENT_QUERY, scope=SCOPE_READ
        ),
        "POST": Operation(
            "Marcação de consulta (exige Idempotency-Key)",
            lambda: dto_schema(AppointmentInfo),
            status=201,
            request=BOOK_INPUT,
            etag=True,
            scope=SCOPE_WRITE,
        ),
    }

    def get(self, request, organization_id):
        params = request.query_params
        page = _service().appointments(
            actor=request.user,
            schedule_id=_uuid(params.get("schedule"), "schedule"),
            patient_id=_uuid(params.get("patient"), "patient"),
            start=_datetime(params.get("start"), "start"),
            end=_datetime(params.get("end"), "end"),
            status=params.get("status") or None,
            cursor=params.get("cursor") or None,
            page_size=_page_size(request),
        )
        return Response({"results": _json(page.items), "next_cursor": page.next_cursor})

    def post(self, request, organization_id):
        fields = _fields(request, BOOK_FIELDS)
        missing = [name for name in ("schedule", "patient", "appointment_type", "starts_at") if not fields.get(name)]
        if missing:
            raise InvalidInput({name: [gettext("Campo obrigatório.")] for name in missing})
        duration = fields.get("duration_minutes")
        if duration not in (None, "") and not str(duration).isdigit():
            raise InvalidInput({"duration_minutes": [gettext("Informe um número inteiro de minutos.")]})
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key:
            raise InvalidInput({"Idempotency-Key": [gettext("Envie o cabeçalho Idempotency-Key.")]})
        with transaction.atomic():
            info = _service().book(
                actor=request.user,
                schedule_id=_uuid(fields["schedule"], "schedule"),
                patient_id=_uuid(fields["patient"], "patient"),
                appointment_type_id=_uuid(fields["appointment_type"], "appointment_type"),
                starts_at=_datetime(fields["starts_at"], "starts_at", required=True),
                duration_minutes=int(duration) if duration not in (None, "") else None,
                fit_in=fields.get("fit_in") in (True, "true", "1"),
                notes=str(fields.get("notes") or ""),
                payment_kind=str(fields.get("payment_kind") or "private"),
                room_id=_uuid(fields.get("room"), "room"),
                idempotency_key=key[:150],
            )
        return _with_etag(Response(_json(info), status=201), info.revision)


class AppointmentAPI(ScopedAPI):
    token_methods = ("GET",)
    token_scopes = {"GET": SCOPE_READ}
    openapi = {
        "GET": Operation("Detalhe da consulta", lambda: dto_schema(AppointmentDetail), etag=True, scope=SCOPE_READ)
    }

    def get(self, request, organization_id, appointment_id):
        detail = _service().appointment(actor=request.user, appointment_id=appointment_id)
        return _with_etag(Response(_json(detail)), detail.appointment.revision)


TRANSITION_INPUT = obj(
    {"reason": string(), "note": string(), "starts_at": string(format="date-time"), "schedule": UUID_SCHEMA},
    required=(),
)


class AppointmentTransitionAPI(ScopedAPI):
    token_methods = ("POST",)
    token_scopes = {"POST": SCOPE_WRITE}
    openapi = {
        "POST": Operation(
            "Mudança de situação da consulta",
            lambda: dto_schema(AppointmentInfo),
            request=TRANSITION_INPUT,
            request_required=False,
            etag=True,
            if_match=True,
            scope=SCOPE_WRITE,
            description=(
                "A transição vem no caminho: confirm, check-in, start, complete, no-show, cancel (reason, note) "
                "ou reschedule (starts_at, schedule; aceita Idempotency-Key)."
            ),
        )
    }

    def post(self, request, organization_id, appointment_id, transition):
        revision = _if_match(request)
        service = _service()
        with transaction.atomic():
            if transition in TRANSITIONS:
                _fields(request, ())
                info = getattr(service, TRANSITIONS[transition])(
                    actor=request.user, appointment_id=appointment_id, expected_revision=revision
                )
            elif transition == "cancel":
                fields = _fields(request, ("reason", "note"))
                info = service.cancel(
                    actor=request.user,
                    appointment_id=appointment_id,
                    reason=str(fields.get("reason") or ""),
                    note=str(fields.get("note") or ""),
                    expected_revision=revision,
                )
            elif transition == "reschedule":
                fields = _fields(request, ("starts_at", "schedule"))
                info = service.reschedule(
                    actor=request.user,
                    appointment_id=appointment_id,
                    starts_at=_datetime(fields.get("starts_at"), "starts_at", required=True),
                    schedule_id=_uuid(fields.get("schedule"), "schedule"),
                    expected_revision=revision,
                    idempotency_key=(request.headers.get("Idempotency-Key") or None),
                )
            else:
                from django.http import Http404

                raise Http404
        return _with_etag(Response(_json(info)), info.revision)
