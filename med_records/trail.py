"""The read trail of the chart: who read clinical content, what, when and from where.

The core audit covers writes only. Every service method that returns clinical content calls
``record_access`` after authorizing the read; the row is written by the service (the reader only
needs read access) and repeated reads of the same target by the same person, from the same
origin, within five minutes are recorded once.

The origin comes from the credential of the request, which the core names in the context's
``source``: ``http`` for a web session, ``http:oidc:<client_id>`` for a native client and
``http:token:<prefix>`` for an API token (#61). Only the client id of a native client is kept: it
identifies an application registered by the operator, never a person or a secret.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

DEDUPLICATION = timedelta(minutes=5)
NATIVE_CLIENT_SOURCE = "http:oidc:"
API_TOKEN_SOURCE = "http:token:"  # noqa: S105 - the source prefix the core gives a token request, not a secret


def request_origin(source: str) -> tuple[str, str]:
    """``(origin, client_id)`` of a read, from the ``source`` of the context."""
    from .models import AccessLog

    if source == "http":
        return AccessLog.Origin.WEB, ""
    if source.startswith(NATIVE_CLIENT_SOURCE):
        return AccessLog.Origin.NATIVE_CLIENT, source.removeprefix(NATIVE_CLIENT_SOURCE)[:64]
    if source.startswith(API_TOKEN_SOURCE):
        return AccessLog.Origin.API_TOKEN, ""
    return AccessLog.Origin.OTHER, ""


def record_access(actor: Any, chart: Any, action: str, target: Any = None) -> None:
    """Record a read of clinical content of ``chart`` (a PatientChart), after it was authorized."""
    from skeleton.tenancy.context import current_context

    from .models import AccessLog

    now = timezone.now()
    target_table = target._meta.label_lower if target is not None else ""
    target_id = target.pk if target is not None else None
    origin, client_id = request_origin(current_context().source or "")
    recent = AccessLog.objects.filter(
        chart_id=chart.pk,
        actor_id=actor.pk,
        action=action,
        target_table=target_table,
        target_id=target_id,
        origin=origin,
        client_id=client_id,
        at__gte=now - DEDUPLICATION,
    )
    if recent.exists():
        return
    AccessLog(
        organization_id=chart.organization_id,
        chart_id=chart.pk,
        actor_id=actor.pk,
        action=action,
        target_table=target_table,
        target_id=target_id,
        origin=origin,
        client_id=client_id,
        at=now,
    ).save()
