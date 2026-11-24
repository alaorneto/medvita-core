"""Contributions of the scheduling app to the patient page (tab, summary panel, timeline, data report, setup step).

Each contribution authorizes with the actor's own access: a schedule the actor does not read adds
nothing. Titles and report lines carry dates and statuses only, never notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext, gettext_lazy

TIMELINE_TITLES = {
    "scheduled": gettext_lazy("Consulta agendada"),
    "confirmed": gettext_lazy("Consulta agendada"),
    "arrived": gettext_lazy("Consulta agendada"),
    "in_progress": gettext_lazy("Consulta agendada"),
    "completed": gettext_lazy("Consulta realizada"),
    "no_show": gettext_lazy("Falta"),
    "cancelled": gettext_lazy("Consulta cancelada"),
}
# A walk-in appointment has no time of its own: the timeline says so, and its date is the start of the period.
WALK_IN_TITLE = gettext_lazy("Consulta por ordem de chegada")
WAITING = ("scheduled", "confirmed", "arrived", "in_progress")


def _readable_appointments(actor: Any, patient_id: UUID) -> Any:
    from skeleton.access.policies import authorized_queryset

    from .models import Appointment

    return authorized_queryset(Appointment, user=actor, action="read").filter(patient_id=patient_id)


def timeline_provider(*, actor: Any, patient_id: UUID, before: datetime | None, limit: int) -> tuple[Any, ...]:
    """Appointments of the patient on the schedules the actor reads, newest first."""
    from applications.med_patients.service_api import TimelineEntry

    rows = _readable_appointments(actor, patient_id)
    if before is not None:
        rows = rows.filter(starts_at__lte=before)
    rows = rows.order_by("-starts_at", "-sysid").only("sysid", "starts_at", "status", "mode")[: max(0, int(limit))]
    return tuple(
        TimelineEntry(
            at=row.starts_at,
            source="med_scheduling.appointments",
            kind="appointment",
            title=str(
                WALK_IN_TITLE
                if row.mode == "walk_in" and row.status in WAITING
                else TIMELINE_TITLES.get(row.status, gettext("Consulta"))
            ),
            url_name="med_scheduling:appointment",
            url_args=(str(row.sysid),),
        )
        for row in rows
    )


def data_provider(*, actor: Any, patient_id: UUID) -> tuple[tuple[str, str], ...]:
    """Date, code and status of each appointment the actor reads (no notes, no priority mark).

    A walk-in appointment shows the period it was booked in, which is all the time it has.
    """
    from .templatetags.med_scheduling_labels import scheduling_label

    rows = (
        _readable_appointments(actor, patient_id)
        .order_by("starts_at", "sysid")
        .only("code", "starts_at", "ends_at", "status", "mode")
    )

    def when(row: Any) -> str:
        if row.mode != "walk_in":
            return f"{row.starts_at:%Y-%m-%d %H:%M} UTC"
        period = f"{row.starts_at:%Y-%m-%d %H:%M}–{row.ends_at:%H:%M} UTC"
        return gettext("%(period)s · ordem de chegada") % {"period": period}

    return tuple(
        (
            gettext("Consulta %(code)s") % {"code": row.code},
            f"{when(row)} · {scheduling_label(row.status, 'status')}",
        )
        for row in rows[:500]
    )


def practice_is_set_up(*, actor: Any) -> bool:
    """The setup step is done once the organization has a practice the actor reads."""
    from skeleton.service_api import Forbidden, NotFound

    from .service_api import SchedulingService

    try:
        SchedulingService().practice(actor=actor)
    except (NotFound, Forbidden):
        return False
    return True


def reads_a_schedule(*, actor: Any, patient_id: UUID) -> bool:
    """The summary panel shows only to who reads some schedule (finance reads none)."""
    from .service_api import SchedulingService

    return bool(SchedulingService().schedules(actor=actor))


def summary_context(*, actor: Any, patient_id: UUID) -> dict[str, Any]:
    """The next appointment still to happen and the last one done, on the schedules the actor reads (#136).

    Read by ``SchedulingService`` with the actor's access: ``AppointmentInfo`` never carries the
    notes nor the priority mark. Times are shown in the practice's time zone.
    """
    from django.utils import timezone

    from skeleton.service_api import Forbidden, NotFound

    from .service_api import SchedulingService

    service = SchedulingService()
    now = timezone.now()
    schedules = {row.sysid: row for row in service.schedules(actor=actor, active_only=False)}
    upcoming = service.appointments(actor=actor, patient_id=patient_id, start=now, page_size=50).items
    following = next((row for row in upcoming if row.status in WAITING), None)
    last, cursor = None, None
    for _page in range(40):  # Oldest first: the last page holds the most recent one.
        page = service.appointments(
            actor=actor, patient_id=patient_id, end=now, status="completed", cursor=cursor, page_size=100
        )
        last = page.items[-1] if page.items else last
        cursor = page.next_cursor
        if not cursor:
            break
    try:
        zone = service.practice(actor=actor).timezone
    except (NotFound, Forbidden):
        zone = "UTC"

    def schedule_name(row: Any) -> str:
        schedule = schedules.get(row.schedule_id) if row is not None else None
        return schedule.name if schedule is not None else ""

    return {
        "next_appointment": following,
        "next_walk_in": following is not None and following.mode == "walk_in",
        "next_schedule": schedule_name(following),
        "last_appointment": last,
        "last_schedule": schedule_name(last),
        "can_book": any(row.writable and row.is_active for row in schedules.values()),
        "zone": zone,
    }


def register() -> None:
    from applications.med_patients.service_api import (
        PatientSection,
        SetupStep,
        SummaryPanel,
        register_patient_data_provider,
        register_patient_section,
        register_setup_step,
        register_summary_panel,
        register_timeline_provider,
    )

    register_patient_section(
        PatientSection(
            "med_scheduling.appointments",
            gettext_lazy("Consultas"),
            "med_scheduling:patient_section",
            order=20,
            icon="appointment",
        )
    )
    register_summary_panel(
        SummaryPanel(
            "med_scheduling.appointments",
            gettext_lazy("Consultas"),
            "med_scheduling/_summary_panel.html",
            order=10,
            visible=reads_a_schedule,
            context=summary_context,
            icon="appointment",
        )
    )
    register_timeline_provider("med_scheduling.appointments", timeline_provider)
    register_patient_data_provider("med_scheduling.appointments", data_provider)
    register_setup_step(
        SetupStep(
            "med_scheduling.practice",
            gettext_lazy("Agenda médica"),
            "med_scheduling:setup",
            practice_is_set_up,
            order=20,
        )
    )
