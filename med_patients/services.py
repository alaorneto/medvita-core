"""Internal rules of the patients app. Only ``service_api.py`` (and the gateway operations) call this."""

from __future__ import annotations

import uuid
from typing import Any

from django.utils.translation import gettext

from skeleton.tenancy.context import current_context

from .models import PatientRegistry


def deterministic_id(kind: str, actor: Any, idempotency_key: str) -> uuid.UUID:
    """The sysid a repeatable creation gets from its idempotency key (same actor, same organization)."""
    organization = current_context().organization_id
    return uuid.uuid5(uuid.NAMESPACE_URL, f"med-patients:{kind}:{organization}:{actor.pk}:{idempotency_key}")


def update_registry_record(record: PatientRegistry, *, user: Any, values: dict[str, Any]) -> None:
    """Generic gateway update of a registry: only the name (the spec's write_fields)."""
    from django.core.exceptions import ValidationError

    name = str(values.get("name", record.name)).strip()
    if not name:
        raise ValidationError({"name": gettext("Informe o nome do cadastro.")})
    record.name = name
    record.save(update_fields={"name"})
