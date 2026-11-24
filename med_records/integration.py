"""Contributions of the records app to the patient page (tab, summary panel, timeline, data report).

The tab and the allergies panel of the "Resumo" tab show only to who reads some clinical archive;
the timeline says only "Atendimento registrado" and "Documento emitido", never the kind of
document or any content; the data report lists dates, codes and professionals of the records the
actor reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext, gettext_lazy


def reads_an_archive(*, actor: Any, patient_id: UUID) -> bool:
    from .service_api import RecordsService

    return bool(RecordsService().archives(actor=actor))


def summary_context(*, actor: Any, patient_id: UUID) -> dict[str, Any]:
    """Active allergies (severe first) and medications in use, in the charts of the archives the actor reads (#136).

    Clinical content: the panel shows only to who reads a clinical archive (``reads_an_archive``),
    and ``chart_summary`` records the read in the trail of each chart.
    """
    from .service_api import RecordsService

    service = RecordsService()
    charts = service.charts_for_patient(actor=actor, patient_id=patient_id)
    allergies: list[Any] = []
    medications: list[Any] = []
    for chart in charts[:5]:
        summary = service.chart_summary(actor=actor, chart_id=chart.sysid)
        allergies += summary.allergies
        medications += summary.medications
    allergies.sort(key=lambda row: (row.severity != "severe", row.substance.casefold()))
    return {
        "has_chart": bool(charts),
        "chart_id": charts[0].sysid if charts else None,
        "allergies": tuple(allergies),
        "medications": tuple(medications),
    }


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
        SummaryPanel,
        register_patient_data_provider,
        register_patient_section,
        register_summary_panel,
        register_timeline_provider,
    )

    register_patient_section(
        PatientSection(
            "med_records.chart",
            gettext_lazy("Prontuário"),
            "med_records:patient_section",
            order=30,
            visible=reads_an_archive,
            icon="chart",
        )
    )
    register_summary_panel(
        SummaryPanel(
            "med_records.allergies",
            gettext_lazy("Alergias e medicamentos"),
            "med_records/_summary_panel.html",
            order=20,
            visible=reads_an_archive,
            context=summary_context,
            icon="allergy",
        )
    )
    register_timeline_provider("med_records.records", timeline_provider)
    register_patient_data_provider("med_records.records", data_provider)
