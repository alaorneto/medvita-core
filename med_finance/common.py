"""Small helpers shared by the modules of the finance app (never imported by other apps)."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, as_uuid
from skeleton.tenancy.context import current_context

APP_LABEL = "med_finance"


def key(value: object, field: str = "idempotency_key") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidInput({field: [gettext("Use uma chave de 1 a 200 caracteres.")]})
    return value


def revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise InvalidInput({"expected_revision": [gettext("Informe a revisão inteira do registro.")]})
    return value


def check_revision(record: Any, expected_revision: object) -> None:
    if record.revision != revision(expected_revision):
        raise Conflict("stale_revision")


def deterministic_id(kind: str, actor: Any, idempotency_key: str) -> UUID:
    organization = current_context().organization_id
    return uuid.uuid5(uuid.NAMESPACE_URL, f"med-finance:{kind}:{organization}:{actor.pk}:{idempotency_key}")


def group_ids(value: object, field: str, limit: int = 20) -> tuple[UUID, ...]:
    if not isinstance(value, tuple) or len(value) > limit:
        raise InvalidInput({field: [gettext("Informe até 20 grupos.")]})
    return tuple(dict.fromkeys(as_uuid(item, field=field) for item in value))


def require_access_manager(actor: Any) -> None:
    from skeleton.service_api.access import AccessService

    if "access.manage" not in AccessService().capabilities(actor=actor):
        raise Forbidden()


def row(actor: Any, model: type, row_id: object, *, field: str, write: bool, lock: bool = False) -> Any:
    """A derived row: ``NotFound`` when unreadable, ``Forbidden`` when the actor only reads it."""
    from skeleton.access.policies import authorized_queryset

    pk = as_uuid(row_id, field=field)
    if write:
        rows = authorized_queryset(model, user=actor, action="update")
        if lock:
            rows = rows.select_for_update()
        found = rows.filter(pk=pk).first()
        if found is not None:
            return found
    found = authorized_queryset(model, user=actor, action="read").filter(pk=pk).first()
    if found is None:
        raise NotFound()
    if write:
        raise Forbidden()
    return found


def changes_dict(changes: object) -> dict[str, Any]:
    if not isinstance(changes, tuple) or not all(isinstance(item, tuple) and len(item) == 2 for item in changes):
        raise InvalidInput({"changes": [gettext("Use pares (campo, valor).")]})
    return dict(changes)


def refuse_unknown(values: dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise InvalidInput({name: [gettext("Campo não pode ser alterado por esta operação.")] for name in unknown})


def apply_changes(record: Any, values: dict[str, Any]) -> set[str]:
    """Set the values that really change and save only them; return the changed names."""
    changed = {name for name, value in values.items() if getattr(record, name) != value}
    for name in changed:
        setattr(record, name, values[name])
    record.save(update_fields=changed)
    return changed
