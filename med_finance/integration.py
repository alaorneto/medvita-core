"""Contributions of the finance app to the agenda and the patient page.

The "Receber" action on an appointment, the "Financeiro" tab and the balance panel of the "Resumo"
tab (only for who reads a cash desk), timeline items without amounts, the data subject report
lines and the retention guard of the fiscal records (five years).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

# Fiscal records are kept five years (CTN, art. 173); confirm the term with the accountant.
RETENTION_YEARS = 5


def reads_a_desk(*, actor: Any, patient_id: UUID) -> bool:
    from .service_api import FinanceService

    return bool(FinanceService().desks(actor=actor))


def summary_context(*, actor: Any, patient_id: UUID) -> dict[str, Any]:
    """What the patient still owes on the desks the actor reads, and whether the actor opens a charge (#136)."""
    from .service_api import FinanceService

    service = FinanceService()
    return {
        "balance": service.patient_balance(actor=actor, patient_id=patient_id),
        "can_charge": any(desk.writable for desk in service.desks(actor=actor)),
    }


def _readable(actor: Any, model: type) -> Any:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return authorized_queryset(model, user=actor, action="read")
    except PermissionDenied:
        return model.objects.none()


def timeline_provider(*, actor: Any, patient_id: UUID, before: datetime | None, limit: int) -> tuple[Any, ...]:
    from applications.med_patients.service_api import TimelineEntry

    from .models import Charge, Payment

    size = max(0, int(limit))
    charges = _readable(actor, Charge).filter(patient_id=patient_id, confirmed_at__isnull=False)
    payments = _readable(actor, Payment).filter(charge__patient_id=patient_id, status="registered")
    if before is not None:
        charges = charges.filter(confirmed_at__lte=before)
        payments = payments.filter(received_at__lte=before)
    entries = [
        TimelineEntry(
            at=row.confirmed_at,
            source="med_finance.finance",
            kind="charge",
            title=gettext("Conta emitida"),
            url_name="med_finance:charge",
            url_args=(str(row.pk),),
        )
        for row in charges.order_by("-confirmed_at", "-sysid").only("sysid", "confirmed_at")[:size]
    ] + [
        TimelineEntry(
            at=row.received_at,
            source="med_finance.finance",
            kind="payment",
            title=gettext("Pagamento recebido"),
            url_name="med_finance:charge",
            url_args=(str(row.charge_id),),
        )
        for row in payments.order_by("-received_at", "-sysid").only("sysid", "received_at", "charge_id")[:size]
    ]
    return tuple(sorted(entries, key=lambda entry: entry.at, reverse=True)[:size])


def data_provider(*, actor: Any, patient_id: UUID) -> tuple[tuple[str, str], ...]:
    """Code, date, total and status of each charge, and number and amount of each receipt the actor reads."""
    from skeleton.common.money import format_amount

    from .models import Charge, Receipt

    lines = []
    for row in _readable(actor, Charge).filter(patient_id=patient_id).order_by("created_at", "sysid")[:500]:
        lines.append(
            (
                gettext("Conta %(code)s") % {"code": row.code},
                f"{row.due_date:%Y-%m-%d} · {format_amount(row.total, 'BRL')} · {row.get_status_display()}",
            )
        )
    for row in _readable(actor, Receipt).filter(charge__patient_id=patient_id).order_by("issued_at", "sysid")[:500]:
        lines.append((gettext("Recibo %(number)s") % {"number": row.number}, format_amount(row.amount, "BRL")))
    return tuple(lines)


def retention_guard(*, patient_id: UUID) -> str | None:
    """Veto deleting or anonymizing a patient with a charge or receipt from the last five years."""
    from .models import Charge

    limit = timezone.now() - timedelta(days=365 * RETENTION_YEARS + 2)
    if Charge.objects.filter(patient_id=patient_id, created_at__gte=limit).exists():
        return gettext(
            "O paciente tem conta ou recibo dos últimos 5 anos: a guarda fiscal impede excluir ou anonimizar "
            "o cadastro."
        )
    return None


def register() -> None:
    from applications.med_patients.service_api import (
        PatientSection,
        SummaryPanel,
        register_patient_data_provider,
        register_patient_section,
        register_retention_guard,
        register_summary_panel,
        register_timeline_provider,
    )
    from applications.med_scheduling.service_api import AppointmentAction, register_appointment_action

    from .extension import ChargeOrigin, register_charge_origin

    register_charge_origin(ChargeOrigin("med_scheduling", gettext_lazy("Agenda")))
    register_appointment_action(
        AppointmentAction(
            "med_finance.collect",
            gettext_lazy("Receber"),
            "med_finance:collect",
            statuses=("arrived", "in_progress", "completed"),
            order=20,
            icon="payment",
        )
    )
    register_patient_section(
        PatientSection(
            "med_finance.account",
            gettext_lazy("Financeiro"),
            "med_finance:patient_section",
            order=40,
            visible=reads_a_desk,
            icon="charge",
        )
    )
    register_summary_panel(
        SummaryPanel(
            "med_finance.balance",
            gettext_lazy("Financeiro"),
            "med_finance/_summary_panel.html",
            order=30,
            visible=reads_a_desk,
            context=summary_context,
            icon="charge",
        )
    )
    register_timeline_provider("med_finance.finance", timeline_provider)
    register_patient_data_provider("med_finance.finance", data_provider)
    register_retention_guard("med_finance.retention", retention_guard)
