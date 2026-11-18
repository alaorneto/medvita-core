"""REST API of the finance app, under ``/api/v1/o/<org>/apps/med_finance/``.

Amounts are integers of centavos. Creating a charge and receiving a payment accept
``Idempotency-Key`` (required); receiving needs ``If-Match`` with the charge revision.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils.translation import gettext
from rest_framework.response import Response

from skeleton.api.views import TenantAPI, request_fields
from skeleton.service_api import InvalidInput

from .service_api import ChargeItemInput, FinanceService


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


def _key(request: Any) -> str:
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise InvalidInput({"Idempotency-Key": [gettext("Envie o cabeçalho Idempotency-Key.")]})
    return key[:150]


def _if_match(request: Any) -> int:
    header = request.headers.get("If-Match", "").strip().removeprefix("W/")
    try:
        return int(header.strip('"'))
    except ValueError:
        raise InvalidInput({"If-Match": [gettext("Envie a revisão atual no cabeçalho If-Match.")]}) from None


def _fields(request: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    fields = request_fields(request)
    unknown = sorted(set(fields) - set(allowed))
    if unknown:
        raise InvalidInput({name: [gettext("Campo não aceito.")] for name in unknown})
    return fields


def _uuid(value: Any, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError:
        raise InvalidInput({field: [gettext("Identificador inválido.")]}) from None


def _int(value: Any, field: str, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    if type(value) is int:
        return value
    raise InvalidInput({field: [gettext("Informe um número inteiro (centavos).")]})


class PriceItemsAPI(TenantAPI):
    def get(self, request, organization_id):
        rows = FinanceService().price_items(actor=request.user, query=request.query_params.get("q", "")[:100])
        return Response({"results": _json(rows)})


class ChargesAPI(TenantAPI):
    def get(self, request, organization_id):
        params = request.query_params
        size = params.get("page_size", "")
        page = FinanceService().charges(
            actor=request.user,
            patient_id=_uuid(params.get("patient"), "patient"),
            status=params.get("status") or None,
            cursor=params.get("cursor") or None,
            page_size=int(size) if size.isdigit() else 50,
        )
        return Response({"results": _json(page.items), "next_cursor": page.next_cursor})

    def post(self, request, organization_id):
        fields = _fields(request, ("patient", "items", "payer_name", "payer_document", "note", "confirm"))
        items = fields.get("items")
        if not isinstance(items, list) or not items:
            raise InvalidInput({"items": [gettext("Informe os itens.")]})
        inputs = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {
                "code",
                "description",
                "quantity",
                "unit_amount",
                "discount_amount",
            }:
                raise InvalidInput({"items": [gettext("Item com campo não aceito.")]})
            inputs.append(
                ChargeItemInput(
                    code=str(item.get("code") or ""),
                    description=str(item.get("description") or ""),
                    quantity=_int(item.get("quantity"), "quantity", 1),
                    unit_amount=_int(item.get("unit_amount"), "unit_amount"),
                    discount_amount=_int(item.get("discount_amount"), "discount_amount", 0),
                )
            )
        with transaction.atomic():
            detail = FinanceService().create_charge(
                actor=request.user,
                patient_id=_uuid(fields.get("patient"), "patient"),
                items=tuple(inputs),
                payer_name=str(fields.get("payer_name") or ""),
                payer_document=str(fields.get("payer_document") or ""),
                note=str(fields.get("note") or ""),
                confirm=fields.get("confirm", True) is not False,
                idempotency_key=_key(request),
            )
        response = Response(_json(detail), status=201)
        response["ETag"] = f'"{detail.charge.revision}"'
        return response


class ChargeAPI(TenantAPI):
    def get(self, request, organization_id, charge_id):
        detail = FinanceService().charge(actor=request.user, charge_id=charge_id)
        response = Response(_json(detail))
        response["ETag"] = f'"{detail.charge.revision}"'
        return response


class PaymentsAPI(TenantAPI):
    def get(self, request, organization_id, charge_id):
        return Response({"results": _json(FinanceService().payments(actor=request.user, charge_id=charge_id))})

    def post(self, request, organization_id, charge_id):
        revision = _if_match(request)
        fields = _fields(request, ("method", "amount", "installments", "authorization_code"))
        with transaction.atomic():
            payment = FinanceService().register_payment(
                actor=request.user,
                charge_id=charge_id,
                method=str(fields.get("method") or ""),
                amount=_int(fields.get("amount"), "amount"),
                installments=_int(fields.get("installments"), "installments", 1),
                authorization_code=str(fields.get("authorization_code") or ""),
                expected_revision=revision,
                idempotency_key=_key(request),
            )
        return Response(_json(payment), status=201)


class ReceiptAPI(TenantAPI):
    def get(self, request, organization_id, receipt_id):
        return Response(_json(FinanceService().receipt(actor=request.user, receipt_id=receipt_id)))
