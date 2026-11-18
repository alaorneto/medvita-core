"""The legal retention of the chart, as a guard registered with the patients app."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext

# Lei 13.787/2018, art. 6º: the chart is kept for at least 20 years after the last record.
RETENTION_YEARS = 20


def retention_guard(*, patient_id: UUID) -> str | None:
    """Veto deleting or anonymizing a patient with a chart entry less than 20 years old.

    A rule of the system, not of the actor: it reads the charts of the current organization (the
    caller's context, never another one) with the default manager.
    """
    from .models import PatientChart

    limit = timezone.now() - timedelta(days=365 * RETENTION_YEARS + RETENTION_YEARS // 4)
    recent: Any = PatientChart.objects.filter(patient_id=patient_id, last_entry_at__gte=limit)
    if recent.exists():
        return gettext(
            "O prontuário deste paciente tem registro dos últimos 20 anos: a guarda legal (Lei 13.787/2018) "
            "impede excluir ou anonimizar o cadastro. Restrinja o tratamento, se for o caso."
        )
    return None
