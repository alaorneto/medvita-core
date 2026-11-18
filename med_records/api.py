"""Read-only REST API of the records app, under ``/api/v1/o/<org>/apps/med_records/``.

Clinical writing happens only on the pages. The detail of an encounter or document carries the
clinical content and records the read in the trail; lists carry headers only.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext
from rest_framework.response import Response

from skeleton.api.views import TenantAPI
from skeleton.service_api import InvalidInput

from .service_api import RecordsService


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


class ChartsAPI(TenantAPI):
    def get(self, request, organization_id):
        patient = request.query_params.get("patient", "")
        try:
            patient_id = UUID(patient)
        except ValueError:
            raise InvalidInput({"patient": [gettext("Informe o paciente.")]}) from None
        rows = RecordsService().charts_for_patient(actor=request.user, patient_id=patient_id)
        return _no_store(Response({"results": _json(rows)}))


class EncountersAPI(TenantAPI):
    def get(self, request, organization_id, chart_id):
        size = request.query_params.get("page_size", "")
        page = RecordsService().encounters(
            actor=request.user,
            chart_id=chart_id,
            cursor=request.query_params.get("cursor") or None,
            page_size=int(size) if size.isdigit() else 50,
        )
        return _no_store(Response({"results": _json(page.items), "next_cursor": page.next_cursor}))


class EncounterAPI(TenantAPI):
    def get(self, request, organization_id, encounter_id):
        info = RecordsService().encounter(actor=request.user, encounter_id=encounter_id)
        return _no_store(Response(_json(info)))


class DocumentAPI(TenantAPI):
    def get(self, request, organization_id, document_id):
        info = RecordsService().document(actor=request.user, document_id=document_id)
        return _no_store(Response(_json(info)))
