"""Read-only REST API of the records app, under ``/api/v1/o/<org>/apps/med_records/``.

Clinical writing happens only on the pages: a token reaches only GET (``token_methods``) with the
``records:read`` scope, and every other method is refused to it. The detail of an encounter or
document carries the clinical content and records the read in the trail, with the origin of the
request (web session, native client or API token); lists carry headers only.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext
from rest_framework.response import Response

from skeleton.api.openapi import INTEGER, Operation, results, string
from skeleton.api.openapi import UUID as UUID_SCHEMA
from skeleton.service_api import InvalidInput

from .api_support import SCOPE_READ, ScopedAPI, cursor_page, dto_schema
from .service_api import ChartInfo, DocumentInfo, EncounterHeader, EncounterInfo, RecordsService


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


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


class ReadOnlyAPI(ScopedAPI):
    token_methods = ("GET",)
    token_scopes = {"GET": SCOPE_READ}


class ChartsAPI(ReadOnlyAPI):
    openapi = {
        "GET": Operation(
            "Prontuários do paciente",
            lambda: results(dto_schema(ChartInfo)),
            query=(("patient", UUID_SCHEMA, "Paciente (obrigatório)"),),
            scope=SCOPE_READ,
        )
    }

    def get(self, request, organization_id):
        patient = request.query_params.get("patient", "")
        try:
            patient_id = UUID(patient)
        except ValueError:
            raise InvalidInput({"patient": [gettext("Informe o paciente.")]}) from None
        rows = RecordsService().charts_for_patient(actor=request.user, patient_id=patient_id)
        return _no_store(Response({"results": _json(rows)}))


class EncountersAPI(ReadOnlyAPI):
    openapi = {
        "GET": Operation(
            "Atendimentos do prontuário, só cabeçalhos",
            lambda: cursor_page(dto_schema(EncounterHeader)),
            query=(
                ("cursor", string(), "Cursor devolvido pela página anterior"),
                ("page_size", INTEGER, "Tamanho da página"),
            ),
            scope=SCOPE_READ,
        )
    }

    def get(self, request, organization_id, chart_id):
        size = request.query_params.get("page_size", "")
        page = RecordsService().encounters(
            actor=request.user,
            chart_id=chart_id,
            cursor=request.query_params.get("cursor") or None,
            page_size=int(size) if size.isdigit() else 50,
        )
        return _no_store(Response({"results": _json(page.items), "next_cursor": page.next_cursor}))


class EncounterAPI(ReadOnlyAPI):
    openapi = {
        "GET": Operation(
            "Atendimento com o conteúdo clínico (registra a leitura)",
            lambda: dto_schema(EncounterInfo),
            scope=SCOPE_READ,
        )
    }

    def get(self, request, organization_id, encounter_id):
        info = RecordsService().encounter(actor=request.user, encounter_id=encounter_id)
        return _no_store(Response(_json(info)))


class DocumentAPI(ReadOnlyAPI):
    openapi = {
        "GET": Operation(
            "Documento com o conteúdo clínico (registra a leitura)", lambda: dto_schema(DocumentInfo), scope=SCOPE_READ
        )
    }

    def get(self, request, organization_id, document_id):
        info = RecordsService().document(actor=request.user, document_id=document_id)
        return _no_store(Response(_json(info)))
