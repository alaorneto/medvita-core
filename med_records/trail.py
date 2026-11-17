"""The read trail of the chart: who read clinical content, what and when.

The core audit covers writes only. Every service method that returns clinical content calls
``record_access`` after authorizing the read; the row is written by the service (the reader only
needs read access) and repeated reads of the same target by the same person within five minutes
are recorded once.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

DEDUPLICATION = timedelta(minutes=5)


def record_access(actor: Any, chart: Any, action: str, target: Any = None) -> None:
    """Record a read of clinical content of ``chart`` (a PatientChart), after it was authorized."""
    from .models import AccessLog

    now = timezone.now()
    target_table = target._meta.label_lower if target is not None else ""
    target_id = target.pk if target is not None else None
    recent = AccessLog.objects.filter(
        chart_id=chart.pk,
        actor_id=actor.pk,
        action=action,
        target_table=target_table,
        target_id=target_id,
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
        at=now,
    ).save()
