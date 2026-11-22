"""The only module of the scheduling app that talks to the core calendar (``skeleton_calendar``).

Each schedule owns a shared calendar with the same access; appointments and blocks are projected
there as managed events. A projected title names the kind of appointment and its code, never the
patient: the calendar shows "Ocupado" to everyone but the owner and the organizer anyway. A walk-in
session is one event that says how many patients it has, instead of one event per appointment.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from uuid import UUID

from skeleton.contrib.calendar.service_api import CalendarService

APP_LABEL = "med_scheduling"
CALENDAR_TABLE = "skeleton_calendar.calendar"
SCHEDULE_TABLE = "med_scheduling.schedule"


def create_calendar(
    actor: Any,
    *,
    name: str,
    owner_user_id: UUID,
    timezone: str,
    writer_group_ids: tuple[UUID, ...],
    reader_group_ids: tuple[UUID, ...],
    idempotency_key: str,
) -> UUID:
    info = CalendarService().create_shared_calendar(
        actor=actor,
        name=name,
        owner_user_id=owner_user_id,
        timezone=timezone,
        writer_group_ids=writer_group_ids,
        reader_group_ids=reader_group_ids,
        idempotency_key=f"med_scheduling:schedule:{idempotency_key}"[:200],
    )
    return info.sysid


def readable_calendars(actor: Any) -> tuple[Any, ...]:
    """The calendars of the core the actor reads, creating none; nothing without the table permission."""
    from skeleton.service_api import Forbidden

    try:
        return CalendarService().calendars(actor=actor)
    except Forbidden:
        return ()


def _grants(
    access: Any,
    actor: Any,
    *,
    table_key: str,
    record_id: UUID,
    groups: Iterable[str],
    users: Iterable[str],
    actions: tuple[str, ...],
    grant: bool,
) -> None:
    method = access.grant_record_access if grant else access.revoke_record_access
    for group in groups:
        for action in actions:
            method(actor=actor, table_key=table_key, record_id=record_id, action=action, group_id=UUID(group))
    for user in users:
        for action in actions:
            method(actor=actor, table_key=table_key, record_id=record_id, action=action, membership_user_id=UUID(user))


def mirror_access(
    actor: Any,
    schedule: Any,
    *,
    writer_groups: set[str],
    reader_groups: set[str],
    writer_users: set[str],
) -> None:
    """Make the record grants of the schedule and of its calendar equal to the given sets."""
    from skeleton.service_api.access import AccessService

    access = AccessService()
    old = {
        "writers": set(schedule.writer_groups),
        "readers": set(schedule.reader_groups),
        "users": set(schedule.writer_users),
    }
    for table_key, record_id in ((SCHEDULE_TABLE, schedule.pk), (CALENDAR_TABLE, schedule.calendar_id)):
        _grants(
            access,
            actor,
            table_key=table_key,
            record_id=record_id,
            groups=old["writers"] - writer_groups,
            users=old["users"] - writer_users,
            actions=("update", "read"),
            grant=False,
        )
        _grants(
            access,
            actor,
            table_key=table_key,
            record_id=record_id,
            groups=old["readers"] - reader_groups - writer_groups,
            users=(),
            actions=("read",),
            grant=False,
        )
        _grants(
            access,
            actor,
            table_key=table_key,
            record_id=record_id,
            groups=writer_groups,
            users=writer_users,
            actions=("read", "update"),
            grant=True,
        )
        _grants(
            access,
            actor,
            table_key=table_key,
            record_id=record_id,
            groups=reader_groups - writer_groups,
            users=(),
            actions=("read",),
            grant=True,
        )


def source_path(schedule_id: UUID, appointment_id: UUID | None = None) -> str:
    if appointment_id is None:
        return f"apps/{APP_LABEL}/schedules/{schedule_id}/"
    return f"apps/{APP_LABEL}/appointments/{appointment_id}/"


def put_event(
    actor: Any,
    *,
    source_key: str,
    calendar_id: UUID,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    tzid: str,
    attendee_user_ids: tuple[UUID, ...],
    path: str,
) -> None:
    CalendarService().put_managed_event(
        actor=actor,
        source_app=APP_LABEL,
        source_key=source_key,
        calendar_id=calendar_id,
        data={"title": title, "starts_at": starts_at, "ends_at": ends_at, "tzid": tzid, "is_private": True},
        attendee_user_ids=attendee_user_ids,
        source_path=path,
    )


def session_key(schedule_id: UUID, day: date, minute: int) -> str:
    """The key of the event of a walk-in session: the schedule, the local day and the minute its period starts."""
    return f"session:{schedule_id}:{day:%Y%m%d}:{minute}"


def session_path(schedule_id: UUID, day: date) -> str:
    return f"apps/{APP_LABEL}/schedules/{schedule_id}/queue/{day.isoformat()}/"


def put_session_event(
    actor: Any,
    *,
    schedule_id: UUID,
    calendar_id: UUID,
    day: date,
    minute: int,
    count: int,
    starts_at: datetime,
    ends_at: datetime | None,
    tzid: str,
    attendee_user_ids: tuple[UUID, ...],
) -> None:
    """One event for a whole walk-in session, saying how many patients it has; with none, no event.

    The title never names a patient nor an appointment: "Ordem de chegada · N pacientes".
    """
    from django.utils.translation import ngettext

    key = session_key(schedule_id, day, minute)
    if count < 1 or ends_at is None:
        remove_event(actor, source_key=key)
        return
    title = ngettext("Ordem de chegada · %(count)d paciente", "Ordem de chegada · %(count)d pacientes", count) % {
        "count": count
    }
    put_event(
        actor,
        source_key=key,
        calendar_id=calendar_id,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        tzid=tzid,
        attendee_user_ids=attendee_user_ids,
        path=session_path(schedule_id, day),
    )


def remove_event(actor: Any, *, source_key: str) -> None:
    CalendarService().remove_managed_event(actor=actor, source_app=APP_LABEL, source_key=source_key)


def managed_event(actor: Any, *, source_key: str) -> Any:
    return CalendarService().managed_event(actor=actor, source_app=APP_LABEL, source_key=source_key)


def busy_of_people(actor: Any, *, user_ids: tuple[UUID, ...], start: datetime, end: datetime) -> tuple[Any, ...]:
    if not user_ids:
        return ()
    return CalendarService().free_busy(actor=actor, user_ids=user_ids, start=start, end=end, include_attending=True)
