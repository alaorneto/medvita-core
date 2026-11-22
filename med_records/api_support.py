"""What the REST views of the app share: the token scope of each method and the OpenAPI of the DTOs.

A view lists in ``token_methods`` the methods a token may call and, in ``token_scopes``, the
named scope each of them needs (registered in ``registration.register_token_scopes``). A session
passes; a token without the scope gets 403 (``permission_denied``, "O token não tem o escopo exigido.") before the view runs. The
scope only narrows: the service still authorizes the person's role, exactly as for a session.

``dto_schema`` turns a DTO of the service into the JSON Schema of its JSON form, so the
``openapi`` declaration of a view follows the DTO instead of being kept by hand.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from django.utils.translation import gettext

from skeleton.api.openapi import ANY, BOOLEAN, DATETIME, INTEGER, OBJECT, array, nullable, obj, string
from skeleton.api.openapi import UUID as UUID_SCHEMA
from skeleton.api.views import TenantAPI
from skeleton.service_api import Forbidden
from skeleton.tenancy.context import current_context

# Reading only: clinical writing stays on the pages, so the API has no write scope.
SCOPE_READ = "records:read"


class ScopedAPI(TenantAPI):
    token_scopes: ClassVar[dict[str, str]] = {}

    def check_permissions(self, request: Any) -> None:
        super().check_permissions(request)
        scopes = current_context().credential_scopes
        if scopes is None:
            return
        scope = self.token_scopes.get(request.method)
        if scope is None or scope not in scopes:
            raise Forbidden(gettext("O token não tem o escopo exigido."))


_SCALARS: dict[Any, dict[str, Any]] = {
    str: string(),
    int: INTEGER,
    bool: BOOLEAN,
    UUID: UUID_SCHEMA,
    datetime: DATETIME,
    date: string(format="date"),
    Any: ANY,
    object: ANY,
}


def _schema(kind: Any) -> dict[str, Any]:
    if kind in _SCALARS:
        return dict(_SCALARS[kind])
    if dataclasses.is_dataclass(kind):
        return dto_schema(kind)
    origin = typing.get_origin(kind)
    arguments = typing.get_args(kind)
    if origin in (types.UnionType, typing.Union):
        present = [argument for argument in arguments if argument is not type(None)]
        inner = _schema(present[0]) if len(present) == 1 else {"anyOf": [_schema(item) for item in present]}
        return nullable(inner)
    if origin in (tuple, list):
        if origin is list or (len(arguments) == 2 and arguments[1] is Ellipsis):
            return array(_schema(arguments[0]) if arguments else ANY)
        items = [_schema(argument) for argument in arguments]
        return {"type": "array", "prefixItems": items, "minItems": len(items), "maxItems": len(items)}
    if origin is dict or kind is dict:
        return dict(OBJECT)
    raise TypeError(f"No JSON Schema for {kind!r}")


def dto_schema(dto: type, *, required: tuple[str, ...] | None = None) -> dict[str, Any]:
    """The closed JSON object of a DTO: every field with its JSON type, all required by default."""
    hints = typing.get_type_hints(dto)
    return obj({field.name: _schema(hints[field.name]) for field in dataclasses.fields(dto)}, required=required)


def cursor_page(item: dict[str, Any]) -> dict[str, Any]:
    """``{"results": [...], "next_cursor": ...}`` of the lists paginated by cursor."""
    return obj({"results": array(item), "next_cursor": nullable(string())})
