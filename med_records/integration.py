"""Contributions of the records app to the patient page (tab, timeline, data report).

The tab shows only to who reads some clinical archive; the timeline says only "Atendimento
registrado" and "Documento emitido", never the kind of document or any content; the data report
lists dates, codes and professionals of the records the actor reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext, gettext_lazy


def reads_an_archive(*, actor: Any, patient_id: UUID) -> bool:
    from .service_api import RecordsService

    return bool(RecordsService().archives(actor=actor))


def _readable(actor: Any, model: type, patient_id: UUID) -> Any:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return authorized_queryset(model, user=actor, action="read").filter(
            patient_id=patient_id, sealed_at__isnull=False
        )
    except PermissionDenied:
        return model.objects.none()


def timeline_provider(*, actor: Any, patient_id: UUID, before: datetime | None, limit: int) -> tuple[Any, ...]:
    from applications.med_patients.service_api import TimelineEntry

    from .models import ClinicalDocument, Encounter

    size = max(0, int(limit))
    encounters = _readable(actor, Encounter, patient_id)
    documents = _readable(actor, ClinicalDocument, patient_id)
    if before is not None:
        encounters = encounters.filter(sealed_at__lte=before)
        documents = documents.filter(sealed_at__lte=before)
    entries = [
        TimelineEntry(
            at=row.sealed_at,
            source="med_records.records",
            kind="encounter",
            title=gettext("Atendimento registrado"),
            url_name="med_records:encounter",
            url_args=(str(row.pk),),
        )
        for row in encounters.order_by("-sealed_at", "-sysid").only("sysid", "sealed_at")[:size]
    ] + [
        TimelineEntry(
            at=row.sealed_at,
            source="med_records.records",
            kind="document",
            title=gettext("Documento emitido"),
            url_name="med_records:document",
            url_args=(str(row.pk),),
        )
        for row in documents.order_by("-sealed_at", "-sysid").only("sysid", "sealed_at")[:size]
    ]
    return tuple(sorted(entries, key=lambda entry: entry.at, reverse=True)[:size])


def data_provider(*, actor: Any, patient_id: UUID) -> tuple[tuple[str, str], ...]:
    """Date, code and professional of each signed encounter and issued document the actor reads.

    The clinical content is not in the automatic report: the professional hands over the copy of
    the chart by printing the records (docs/compliance.md).
    """
    from .models import ClinicalDocument, Encounter

    lines = []
    for row in _readable(actor, Encounter, patient_id).order_by("occurred_at", "sysid")[:500]:
        lines.append(
            (gettext("Atendimento %(code)s") % {"code": row.code}, f"{row.occurred_at:%Y-%m-%d} · {row.author_name}")
        )
    for row in _readable(actor, ClinicalDocument, patient_id).order_by("issued_at", "sysid")[:500]:
        lines.append(
            (gettext("Documento %(code)s") % {"code": row.code}, f"{row.issued_at:%Y-%m-%d} · {row.author_name}")
        )
    return tuple(lines)


def register() -> None:
    from applications.med_patients.service_api import (
        PatientSection,
        register_patient_data_provider,
        register_patient_section,
        register_timeline_provider,
    )

    register_patient_section(
        PatientSection(
            "med_records.chart",
            gettext_lazy("Prontuário"),
            "med_records:patient_section",
            order=30,
            visible=reads_an_archive,
        )
    )
    register_timeline_provider("med_records.records", timeline_provider)
    register_patient_data_provider("med_records.records", data_provider)
