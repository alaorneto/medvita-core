"""Service API of the scheduling app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Besides ``SchedulingService`` it re-exports
the registry other apps call in ``ready()`` to add actions to an appointment (``extension.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import (
    Conflict,
    Forbidden,
    InvalidInput,
    NotFound,
    Page,
    ServiceAPI,
    as_utc,
    as_uuid,
    paginate,
    service_method,
)

from . import common
from .extension import AppointmentAction, register_appointment_action
from .models import (
    Appointment,
    AppointmentType,
    AvailabilityRule,
    AvailabilityRuleType,
    Mode,
    PaymentKind,
    Practice,
    Professional,
    Room,
    Schedule,
    ScheduleAppointmentType,
    ScheduleBlock,
    WaitlistEntry,
)

APP_LABEL = common.APP_LABEL
APP_ID = "io.medvita.scheduling"
PRACTICE_TABLE = "med_scheduling.practice"
SCHEDULE_TABLE = "med_scheduling.schedule"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (PRACTICE_TABLE, SCHEDULE_TABLE, "skeleton_calendar.calendar")
QUOTA_ACTIVE_PROFESSIONALS = "med_scheduling.active_professionals"
Scalar = str | int | bool | date | None
BOOKED = Mode.BOOKED.value
WALK_IN = Mode.WALK_IN.value

__all__ = [
    "APP_ID",
    "AppointmentAction",
    "AppointmentActionInfo",
    "AppointmentDetail",
    "AppointmentInfo",
    "AppointmentTypeInfo",
    "AvailabilityRuleInfo",
    "AvailabilityRuleInput",
    "BlockInfo",
    "DayAgenda",
    "DayException",
    "DayWindowInput",
    "PeriodPlan",
    "PlanConflict",
    "PracticeInfo",
    "ProfessionalInfo",
    "QueueEntry",
    "QueueSession",
    "RoomInfo",
    "ScheduleInfo",
    "ScheduleTypeInfo",
    "ScheduleTypeInput",
    "SchedulingService",
    "Slot",
    "WaitlistInfo",
    "register_appointment_action",
]


# --------------------------------------------------------------------------------------- DTOs


@dataclass(frozen=True, slots=True)
class PracticeInfo:
    sysid: UUID
    name: str
    legal_name: str
    tax_id: str
    phone: str
    email: str
    address: str
    city: str
    state: str
    timezone: str
    revision: int
    writable: bool = False


def practice_info(practice: Practice, *, writable: bool = False) -> PracticeInfo:
    return PracticeInfo(
        practice.pk,
        practice.name,
        practice.legal_name,
        practice.tax_id,
        practice.phone,
        practice.email,
        practice.address,
        practice.city,
        practice.state,
        practice.timezone,
        practice.revision,
        writable,
    )


@dataclass(frozen=True, slots=True)
class ProfessionalInfo:
    sysid: UUID
    practice_id: UUID
    user_id: UUID | None
    display_name: str
    council: str
    council_number: str
    council_state: str
    council_label: str
    specialty: str
    rqe: str
    tax_id: str
    is_active: bool
    revision: int


def professional_info(row: Professional) -> ProfessionalInfo:
    return ProfessionalInfo(
        row.pk,
        row.practice_id,
        row.user_id,
        row.display_name,
        row.council,
        row.council_number,
        row.council_state,
        row.council_label,
        row.specialty,
        row.rqe,
        row.tax_id,
        row.is_active,
        row.revision,
    )


@dataclass(frozen=True, slots=True)
class RoomInfo:
    sysid: UUID
    practice_id: UUID
    name: str
    kind: str
    is_active: bool
    revision: int


def room_info(row: Room) -> RoomInfo:
    return RoomInfo(row.pk, row.practice_id, row.name, row.kind, row.is_active, row.revision)


@dataclass(frozen=True, slots=True)
class AppointmentTypeInfo:
    sysid: UUID
    practice_id: UUID
    code: str
    name: str
    duration_minutes: int
    color: str
    billing_code: str
    requires_room: bool
    is_active: bool
    revision: int
    payment_kind: str = "private"


def type_info(row: AppointmentType) -> AppointmentTypeInfo:
    return AppointmentTypeInfo(
        row.pk,
        row.practice_id,
        row.code,
        row.name,
        row.duration_minutes,
        row.color,
        row.billing_code,
        row.requires_room,
        row.is_active,
        row.revision,
        str(row.payment_kind),
    )


@dataclass(frozen=True, slots=True)
class ScheduleTypeInput:
    """A kind of appointment a schedule takes: its own duration there (``None``: the one of the kind) and the modes."""

    appointment_type_id: UUID
    duration_minutes: int | None = None
    allow_booked: bool = True
    allow_walk_in: bool = True


@dataclass(frozen=True, slots=True)
class ScheduleTypeInfo:
    """A kind of appointment as one schedule takes it.

    ``duration_minutes`` is the duration in force there: ``own_duration`` when the schedule has one,
    otherwise the one of the kind. ``configured`` is False while the schedule takes every active kind.
    """

    appointment_type_id: UUID
    duration_minutes: int
    own_duration: int | None
    allow_booked: bool
    allow_walk_in: bool
    configured: bool


@dataclass(frozen=True, slots=True)
class ScheduleInfo:
    sysid: UUID
    practice_id: UUID
    name: str
    professional_id: UUID | None
    room_id: UUID | None
    calendar_id: UUID
    slot_minutes: int
    booking_horizon_days: int
    is_active: bool
    revision: int
    writable: bool = False


def schedule_info(row: Schedule, *, writable: bool = False) -> ScheduleInfo:
    return ScheduleInfo(
        row.pk,
        row.practice_id,
        row.name,
        row.professional_id,
        row.room_id,
        row.calendar_id,
        row.slot_minutes,
        row.booking_horizon_days,
        row.is_active,
        row.revision,
        writable,
    )


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """A calendar of the core the actor reads, as the schedules page lists it.

    ``schedule_id`` names the schedule the calendar belongs to. It is ``None`` for any other
    calendar (a personal or a shared one), which holds common events of the core: no appointment
    rule applies to it. ``is_own`` marks the actor's own personal calendar.
    """

    calendar_id: UUID
    name: str
    kind: str
    is_own: bool = False
    schedule_id: UUID | None = None
    schedule_is_active: bool = True


@dataclass(frozen=True, slots=True)
class AvailabilityRuleInput:
    """A weekly window: ``weekday`` 0 (Monday) to 6, minutes of the day in the practice's time zone.

    ``appointment_type_ids`` are the kinds the period takes; none means every kind the schedule
    takes. ``appointment_type_id`` is the older way of naming a single kind and joins the set.
    ``mode`` is "booked" (each appointment has its time) or "walk_in" (patients are seen in the
    order they arrive); a walk-in period may say its ``capacity``, how many appointments a day of
    it takes.
    """

    weekday: int
    start_minute: int
    end_minute: int
    valid_from: date
    valid_until: date | None = None
    appointment_type_id: UUID | None = None
    appointment_type_ids: tuple[UUID, ...] = ()
    mode: str = "booked"
    capacity: int | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityRuleInfo:
    sysid: UUID
    schedule_id: UUID
    weekday: int
    start_minute: int
    end_minute: int
    valid_from: date
    valid_until: date | None
    appointment_type_id: UUID | None
    appointment_type_ids: tuple[UUID, ...] = ()
    mode: str = "booked"
    capacity: int | None = None
    on_date: date | None = None  # the day of the exception the window belongs to; none in the weekly grid


def rule_info(row: AvailabilityRule, kinds: Any = ()) -> AvailabilityRuleInfo:
    """A window with the kinds its period lists; ``appointment_type_id`` answers while there is a single one."""
    ids = _kinds_of_rule(row, kinds)
    return AvailabilityRuleInfo(
        row.pk,
        row.schedule_id,
        row.weekday,
        row.start_minute,
        row.end_minute,
        row.valid_from,
        row.valid_until,
        ids[0] if len(ids) == 1 else None,
        ids,
        str(row.mode),
        row.capacity,
        row.on_date,
    )


def _kinds_of_rule(row: AvailabilityRule, kinds: Any = ()) -> tuple[UUID, ...]:
    """The kinds of a window: the link rows plus the single kind an older row still carries."""
    found = set(kinds)
    if row.appointment_type_id is not None:
        found.add(row.appointment_type_id)
    return tuple(sorted(found, key=str))


@dataclass(frozen=True, slots=True)
class BlockInfo:
    sysid: UUID
    schedule_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str
    note: str
    revision: int


def block_info(row: ScheduleBlock) -> BlockInfo:
    from skeleton.service_api import as_utc

    return BlockInfo(
        row.pk, row.schedule_id, as_utc(row.starts_at), as_utc(row.ends_at), row.reason, row.note, row.revision
    )


@dataclass(frozen=True, slots=True)
class Slot:
    """A free time; ``appointment_type_ids`` are the kinds its period takes (none: every kind of the schedule)."""

    starts_at: datetime
    ends_at: datetime
    schedule_id: UUID
    appointment_type_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class AppointmentInfo:
    """An appointment as lists show it: never the notes of the reception nor the priority mark.

    In a walk-in appointment (``mode`` "walk_in") ``starts_at`` and ``ends_at`` are the bounds of
    its period, not a time of its own; ``duration_minutes`` is what was planned for it and
    ``arrival_number`` its number in the session once the patient arrives.
    """

    sysid: UUID
    code: str
    schedule_id: UUID
    patient_id: UUID
    appointment_type_id: UUID
    professional_id: UUID | None
    room_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    status: str
    is_fit_in: bool
    billing_code: str
    payment_kind: str
    rescheduled_from_id: UUID | None
    revision: int
    mode: str = "booked"
    duration_minutes: int = 0
    arrival_number: int | None = None


def _planned(row: Any) -> int:
    """The minutes planned for an appointment; a row from before the column says them by its interval."""
    return row.duration_minutes or int((row.ends_at - row.starts_at).total_seconds() // 60)


def appointment_info(row: Appointment) -> AppointmentInfo:
    return AppointmentInfo(
        row.pk,
        row.code,
        row.schedule_id,
        row.patient_id,
        row.appointment_type_id,
        row.professional_id,
        row.room_id,
        as_utc(row.starts_at),
        as_utc(row.ends_at),
        row.status,
        row.is_fit_in,
        row.billing_code,
        row.payment_kind,
        row.rescheduled_from_id,
        row.revision,
        str(row.mode),
        _planned(row),
        row.arrival_number,
    )


@dataclass(frozen=True, slots=True)
class AppointmentDetail:
    """One appointment with the notes, the history of its state and the priority mark (sensitive)."""

    appointment: AppointmentInfo
    notes: str
    confirmed_at: datetime | None
    arrived_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str
    cancel_note: str
    writable: bool
    is_priority: bool = False


def appointment_detail(row: Appointment, *, writable: bool) -> AppointmentDetail:
    def stamp(value: datetime | None) -> datetime | None:
        return as_utc(value) if value else None

    return AppointmentDetail(
        appointment_info(row),
        row.notes,
        stamp(row.confirmed_at),
        stamp(row.arrived_at),
        stamp(row.started_at),
        stamp(row.completed_at),
        stamp(row.cancelled_at),
        row.cancel_reason,
        row.cancel_note,
        writable,
        row.is_priority,
    )


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """An appointment of a walk-in session as the queue shows it, with the priority mark (sensitive).

    ``position`` is the place in the call order among those who wait (1 is called next); ``None``
    for whoever is not waiting.
    """

    appointment: AppointmentInfo
    arrived_at: datetime | None
    is_priority: bool
    position: int | None = None


@dataclass(frozen=True, slots=True)
class QueueSession:
    """A walk-in session: a schedule and one of its walk-in periods on a day.

    ``taken`` counts the appointments that use the room of the session (not cancelled, not a
    fit-in) and ``planned_minutes`` adds their durations; ``is_full`` says no other fits.
    ``waiting`` is in the call order (priority first, then the arrival number), ``expected`` (not
    arrived yet) in the order they were booked; ``finished`` gathers who was seen and who missed.
    """

    schedule_id: UUID
    day: date
    starts_at: datetime
    ends_at: datetime
    capacity: int | None
    taken: int
    planned_minutes: int
    open_minutes: int
    is_full: bool
    waiting: tuple[QueueEntry, ...]
    expected: tuple[QueueEntry, ...]
    in_progress: tuple[QueueEntry, ...]
    finished: tuple[QueueEntry, ...]


@dataclass(frozen=True, slots=True)
class PeriodPlan:
    """A period a schedule works on one day, with how much of it is taken.

    ``taken`` counts the appointments of the period that are not cancelled nor a fit-in, and
    ``planned_minutes`` adds their durations; ``open_minutes`` are the minutes no block takes.
    ``is_full`` is about a walk-in period (in booked time the free slots say it).
    ``is_exception`` tells a period that holds only on that day from one of the weekly grid.
    """

    schedule_id: UUID
    day: date
    start_minute: int
    end_minute: int
    starts_at: datetime
    ends_at: datetime
    mode: str
    capacity: int | None
    appointment_type_ids: tuple[UUID, ...]
    taken: int
    planned_minutes: int
    open_minutes: int
    is_full: bool
    is_exception: bool = False


@dataclass(frozen=True, slots=True)
class DayAgenda:
    """A schedule on one day; ``sessions`` are its walk-in sessions, whose appointments are in ``appointments`` too."""

    schedule: ScheduleInfo
    appointments: tuple[AppointmentInfo, ...]
    free: tuple[Slot, ...]
    sessions: tuple[QueueSession, ...] = ()


@dataclass(frozen=True, slots=True)
class DayWindowInput:
    """A period of the exception of a day: minutes of that day on the practice's clock.

    ``mode``, ``capacity`` and ``appointment_type_ids`` mean what they mean in a window of the
    weekly grid (``AvailabilityRuleInput``).
    """

    start_minute: int
    end_minute: int
    mode: str = "booked"
    capacity: int | None = None
    appointment_type_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class DayException:
    """The periods a schedule follows on one day in place of its weekly grid, by start."""

    schedule_id: UUID
    date: date
    windows: tuple[AvailabilityRuleInfo, ...]


@dataclass(frozen=True, slots=True)
class PlanConflict:
    """An appointment that a change of the periods of its day does not hold as it is.

    ``reason`` says what the change does to it. Two are moves the owner confirms: "to_walk_in"
    (it had a time and its period becomes walk-in: it goes to the session) and "to_session" (a
    walk-in one whose period changes its bounds: it follows the period). The others refuse the
    change (``blocking``): "to_booked" (a walk-in one whose period becomes booked time), "outside"
    (no period holds it) and "arrived" (the patient already arrived: the queue keeps its numbers).
    ``starts_at`` and ``ends_at`` are the bounds of the period a move goes to. A move ignores the
    room of the session and the kinds its period lists: ``over_capacity`` and ``kind_not_listed``
    say when it does.
    """

    appointment: AppointmentInfo
    reason: str
    blocking: bool
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    over_capacity: bool = False
    kind_not_listed: bool = False


@dataclass(frozen=True, slots=True)
class AppointmentActionInfo:
    code: str
    label: str
    url_name: str
    order: int


@dataclass(frozen=True, slots=True)
class WaitlistInfo:
    sysid: UUID
    patient_id: UUID
    appointment_type_id: UUID | None
    schedule_id: UUID | None
    preferred_period: str
    earliest_date: date
    latest_date: date | None
    priority: str
    status: str
    note: str
    booked_appointment_id: UUID | None
    created_at: datetime
    revision: int


def waitlist_info(row: WaitlistEntry) -> WaitlistInfo:
    return WaitlistInfo(
        row.pk,
        row.patient_id,
        row.appointment_type_id,
        row.schedule_id,
        row.preferred_period,
        row.earliest_date,
        row.latest_date,
        row.priority,
        row.status,
        row.note,
        row.booked_appointment_id,
        as_utc(row.created_at),
        row.revision,
    )


# ------------------------------------------------------------------------------------ helpers


def _practice(actor: Any, *, write: bool = False, lock: bool = False) -> Practice:
    """The default practice; ``NotFound`` when unreadable or not set up, ``Forbidden`` when only readable."""
    from skeleton.access.policies import authorized_queryset

    if write:
        rows = authorized_queryset(Practice, user=actor, action="update").filter(is_default=True)
        found = (rows.select_for_update() if lock else rows).first()
        if found is not None:
            return found
    found = authorized_queryset(Practice, user=actor, action="read").filter(is_default=True).first()
    if found is None:
        raise NotFound()
    if write:
        raise Forbidden()
    return found


def _practice_writable(actor: Any, practice: Practice) -> bool:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return authorized_queryset(Practice, user=actor, action="update").filter(pk=practice.pk).exists()
    except PermissionDenied:
        return False


def _new_child(actor: Any, model: type, practice: Practice, idempotency_key: str | None, kind: str) -> Any:
    from skeleton.access.policies import require_parent_action

    require_parent_action(model, practice, user=actor, action="create")
    row = model(organization_id=practice.organization_id, practice=practice)
    if idempotency_key is not None:
        row.sysid = common.deterministic_id(kind, actor, common.key(idempotency_key))
    return row


def _schedule(actor: Any, schedule_id: object, *, write: bool = False, lock: bool = False) -> Schedule:
    from skeleton.access.policies import authorized_queryset

    pk = as_uuid(schedule_id, field="schedule_id")
    if write:
        rows = authorized_queryset(Schedule, user=actor, action="update").filter(pk=pk)
        found = (rows.select_for_update() if lock else rows).first()
        if found is not None:
            return found
    found = authorized_queryset(Schedule, user=actor, action="read").filter(pk=pk).first()
    if found is None:
        raise NotFound()
    if write:
        raise Forbidden()
    return found


def _writable_schedule_ids(actor: Any) -> set[UUID]:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return set(authorized_queryset(Schedule, user=actor, action="update").values_list("pk", flat=True))
    except PermissionDenied:
        return set()


def _bump(record: Any) -> None:
    """A new revision for a container whose children changed (the CAS of a whole grid)."""
    record.save(update_fields={"updated_at"})


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidInput({field: [gettext("Use data e hora com fuso.")]})
    return value


def _check_mode(value: object) -> str:
    if not isinstance(value, str) or value not in Mode.values:
        raise InvalidInput({"mode": [gettext("Modo de atendimento desconhecido.")]})
    return str(value)


def _check_flag(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise InvalidInput({field: [gettext("Informe verdadeiro ou falso.")]})
    return value


def _input_kinds(rule: Any) -> frozenset[UUID]:
    ids = rule.appointment_type_ids
    if not isinstance(ids, tuple) or len(ids) > MAX_SCHEDULE_TYPES:
        raise InvalidInput(
            {"appointment_type_ids": [gettext("Informe os tipos do período numa tupla de identificadores.")]}
        )
    found = {as_uuid(value, field="appointment_type_ids") for value in ids}
    if rule.appointment_type_id is not None:
        found.add(as_uuid(rule.appointment_type_id, field="appointment_type_id"))
    return frozenset(found)


def _shape(rule: Any) -> tuple[int, int, int, date, date | None]:
    """What makes a window the same window, in an input and in a row."""
    return (rule.weekday, rule.start_minute, rule.end_minute, rule.valid_from, rule.valid_until)


def _rule_kinds(actor: Any, rules: Any) -> dict[UUID, list[UUID]]:
    """The kinds each window lists, by window, in one query for all of them."""
    from skeleton.access.policies import authorized_queryset

    ids = [rule.pk for rule in rules]
    found: dict[UUID, list[UUID]] = {}
    if not ids:
        return found
    links = authorized_queryset(AvailabilityRuleType, user=actor, action="read").filter(rule_id__in=ids)
    for rule_id, type_id in links.values_list("rule_id", "appointment_type_id"):
        found.setdefault(rule_id, []).append(type_id)
    return found


def _windows(actor: Any, rules: Any) -> list[Any]:
    """The windows of the rules of one or more schedules, each with the kinds its period lists."""
    from .slots import windows_of

    rules = list(rules)
    return windows_of(rules, _rule_kinds(actor, rules))


def _availability(actor: Any, schedule: Schedule) -> tuple[AvailabilityRuleInfo, ...]:
    from skeleton.access.policies import authorized_queryset

    rows = list(
        authorized_queryset(AvailabilityRule, user=actor, action="read")
        .filter(schedule=schedule, on_date__isnull=True)
        .order_by("weekday", "start_minute", "sysid")
    )
    kinds = _rule_kinds(actor, rows)
    return tuple(rule_info(row, kinds.get(row.pk, ())) for row in rows)


def _check_rules(rules: object) -> list[tuple[AvailabilityRuleInput, frozenset[UUID]]]:
    """The windows asked for, by weekday and start, each with its kinds: well formed and not overlapping."""
    if (
        not isinstance(rules, tuple)
        or len(rules) > 100
        or not all(isinstance(rule, AvailabilityRuleInput) for rule in rules)
    ):
        raise InvalidInput({"rules": [gettext("Informe até 100 faixas (AvailabilityRuleInput).")]})
    kinds = {}
    for rule in rules:
        if type(rule.weekday) is not int or not 0 <= rule.weekday <= 6:
            raise InvalidInput({"weekday": [gettext("Dia da semana de 0 (segunda) a 6 (domingo).")]})
        if (
            type(rule.start_minute) is not int
            or type(rule.end_minute) is not int
            or not 0 <= rule.start_minute < rule.end_minute <= 1440
        ):
            raise InvalidInput(
                {"start_minute": [gettext("O fim da faixa precisa ser depois do início, no mesmo dia.")]}
            )
        if not isinstance(rule.valid_from, date) or (
            rule.valid_until is not None and rule.valid_until < rule.valid_from
        ):
            raise InvalidInput({"valid_until": [gettext("A validade termina antes de começar.")]})
        if _check_mode(rule.mode) != WALK_IN and rule.capacity is not None:
            raise InvalidInput({"capacity": [gettext("Só um período de ordem de chegada tem vagas.")]})
        if rule.capacity is not None and (type(rule.capacity) is not int or not 1 <= rule.capacity <= 500):
            raise InvalidInput({"capacity": [gettext("Use de 1 a 500 vagas.")]})
        kinds[id(rule)] = _input_kinds(rule)
    from .slots import collide

    ordered = sorted(rules, key=lambda rule: (rule.weekday, rule.start_minute))
    for index, first in enumerate(ordered):
        if any(collide(first, second) for second in ordered[index + 1 :]):
            raise InvalidInput({"rules": [gettext("Duas faixas da agenda se sobrepõem no mesmo dia.")]})
    return [(rule, kinds[id(rule)]) for rule in ordered]


MAX_SLOT_DAYS = 62
MAX_SCHEDULE_TYPES = 200


def _schedule_type_rows(actor: Any, schedule: Schedule) -> dict[UUID, ScheduleAppointmentType]:
    """The kinds a schedule was configured with, by kind; empty while it takes every active kind."""
    from skeleton.access.policies import authorized_queryset

    rows = authorized_queryset(ScheduleAppointmentType, user=actor, action="read").filter(schedule=schedule)
    return {row.appointment_type_id: row for row in rows}


def _schedule_windows(actor: Any, schedule: Schedule) -> list[Any]:
    """Every window of a schedule, of the weekly grid and of the exceptions of its days, each with its kinds,
    mode and capacity. Which of them a day follows is ``slots.windows_on``."""
    from skeleton.access.policies import authorized_queryset

    return _windows(actor, authorized_queryset(AvailabilityRule, user=actor, action="read").filter(schedule=schedule))


def _blocked(actor: Any, schedule: Schedule, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """The blocks of a schedule that overlap an interval."""
    from skeleton.access.policies import authorized_queryset

    return list(
        authorized_queryset(ScheduleBlock, user=actor, action="read")
        .filter(schedule=schedule, starts_at__lt=end, ends_at__gt=start)
        .values_list("starts_at", "ends_at")
    )


def _type_duration(actor: Any, schedule: Schedule, kind: AppointmentType, *, mode: str = "booked") -> int | None:
    """The duration a schedule gives a kind in ``mode``; ``None`` when the schedule does not take the kind.

    A kind is taken when it is active and the schedule either has no kinds configured or has this
    one with the mode allowed.
    """
    if not kind.is_active:
        return None
    rows = _schedule_type_rows(actor, schedule)
    if not rows:
        return kind.duration_minutes
    row = rows.get(kind.pk)
    if row is None or not (row.allow_booked if mode == "booked" else row.allow_walk_in):
        return None
    return row.duration_minutes or kind.duration_minutes


def _schedule_types(actor: Any, schedule: Schedule) -> tuple[ScheduleTypeInfo, ...]:
    from skeleton.access.policies import authorized_queryset

    kinds = (
        authorized_queryset(AppointmentType, user=actor, action="read")
        .filter(practice_id=schedule.practice_id, is_active=True)
        .order_by("name", "sysid")[:MAX_SCHEDULE_TYPES]
    )
    rows = _schedule_type_rows(actor, schedule)
    if not rows:
        return tuple(ScheduleTypeInfo(kind.pk, kind.duration_minutes, None, True, True, False) for kind in kinds)
    return tuple(
        ScheduleTypeInfo(
            kind.pk,
            rows[kind.pk].duration_minutes or kind.duration_minutes,
            rows[kind.pk].duration_minutes,
            rows[kind.pk].allow_booked,
            rows[kind.pk].allow_walk_in,
            True,
        )
        for kind in kinds
        if kind.pk in rows
    )


def _check_schedule_types(types: object, schedule: Schedule, actor: Any) -> dict[UUID, ScheduleTypeInput]:
    from skeleton.access.policies import authorized_queryset

    if (
        not isinstance(types, tuple)
        or len(types) > MAX_SCHEDULE_TYPES
        or not all(isinstance(item, ScheduleTypeInput) for item in types)
    ):
        raise InvalidInput({"types": [gettext("Informe até 200 tipos (ScheduleTypeInput).")]})
    known = set(
        authorized_queryset(AppointmentType, user=actor, action="read")
        .filter(practice_id=schedule.practice_id, is_active=True)
        .values_list("pk", flat=True)
    )
    wanted: dict[UUID, ScheduleTypeInput] = {}
    for item in types:
        type_id = as_uuid(item.appointment_type_id, field="appointment_type_id")
        if type_id not in known:
            raise InvalidInput({"appointment_type_id": [gettext("Tipo de atendimento desconhecido ou inativo.")]})
        if type_id in wanted:
            raise InvalidInput({"types": [gettext("O mesmo tipo de atendimento aparece duas vezes.")]})
        if item.duration_minutes is not None and (
            type(item.duration_minutes) is not int or not 5 <= item.duration_minutes <= 480
        ):
            raise InvalidInput({"duration_minutes": [gettext("Use de 5 a 480 minutos.")]})
        if type(item.allow_booked) is not bool or type(item.allow_walk_in) is not bool:
            raise InvalidInput({"allow_booked": [gettext("Informe os modos com verdadeiro ou falso.")]})
        if not (item.allow_booked or item.allow_walk_in):
            raise InvalidInput({"allow_booked": [gettext("Marque ao menos um modo de atendimento para o tipo.")]})
        wanted[type_id] = item
    return wanted


def _taken(actor: Any, schedule: Schedule, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Blocks, live appointments and busy intervals of the professional that overlap the window."""
    from skeleton.access.policies import authorized_queryset

    from . import calendar_bridge

    taken = list(
        authorized_queryset(ScheduleBlock, user=actor, action="read")
        .filter(schedule=schedule, starts_at__lt=end, ends_at__gt=start)
        .values_list("starts_at", "ends_at")
    )
    taken += _appointments_taken(actor, schedule, start, end)
    user_id = schedule.professional.user_id if schedule.professional_id else None
    if user_id is not None:
        taken += [
            (block.starts_at, block.ends_at)
            for block in calendar_bridge.busy_of_people(actor, user_ids=(user_id,), start=start, end=end)
        ]
    return taken


def _appointments_taken(
    actor: Any, schedule: Schedule, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Live appointments of the schedule that overlap the window."""
    from skeleton.access.policies import authorized_queryset

    from .transitions import LIVE

    return list(
        authorized_queryset(Appointment, user=actor, action="read")
        .filter(schedule=schedule, status__in=LIVE, starts_at__lt=end, ends_at__gt=start)
        .values_list("starts_at", "ends_at")
    )


def _day_window(day_start: date, day_end: date, timezone: str) -> tuple[datetime, datetime]:
    from datetime import time, timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day_start, time(), tzinfo=zone),
        datetime.combine(day_end + timedelta(days=1), time(), tzinfo=zone),
    )


def _appointment(actor: Any, appointment_id: object, *, write: bool = False, lock: bool = False) -> Appointment:
    return common.row(actor, Appointment, appointment_id, field="appointment_id", write=write, lock=lock)


def _payload(row: Appointment) -> tuple[tuple[str, str], ...]:
    return (
        ("code", row.code),
        ("schedule", str(row.schedule_id)),
        ("patient", str(row.patient_id)),
        ("appointment_type", str(row.appointment_type_id)),
        ("billing_code", row.billing_code),
        ("starts_at", as_utc(row.starts_at).isoformat()),
        ("ends_at", as_utc(row.ends_at).isoformat()),
        ("status", row.status),
        ("mode", str(row.mode)),
    )


def _publish(actor: Any, suffix: str, row: Appointment) -> None:
    from skeleton.service_api.events import EventService

    EventService().publish(
        actor=actor, event_type=f"{APP_LABEL}.appointment_{suffix}", record_id=row.pk, data=_payload(row)
    )


def _project_session(actor: Any, schedule: Schedule, starts_at: datetime) -> None:
    """The walk-in session that starts at ``starts_at`` in the schedule's calendar: how many, never who.

    One event for the session, counting its appointments that are not cancelled, so that it stays
    in the calendar while the patients are seen; with none left the event goes away.
    """
    from zoneinfo import ZoneInfo

    from . import calendar_bridge
    from .transitions import CANCELLED

    rows = Appointment.objects.filter(schedule=schedule, mode=WALK_IN, starts_at=starts_at).exclude(status=CANCELLED)
    ends_at = rows.values_list("ends_at", flat=True).first()
    local = starts_at.astimezone(ZoneInfo(schedule.practice.timezone))
    attendees = ()
    if schedule.professional_id is not None:
        user = Professional.objects.filter(pk=schedule.professional_id).values_list("user_id", flat=True).first()
        attendees = (user,) if user else ()
    calendar_bridge.put_session_event(
        actor,
        schedule_id=schedule.pk,
        calendar_id=schedule.calendar_id,
        day=local.date(),
        minute=local.hour * 60 + local.minute,
        count=rows.count() if ends_at is not None else 0,
        starts_at=starts_at,
        ends_at=ends_at,
        tzid=schedule.practice.timezone,
        attendee_user_ids=attendees,
    )


def _project(actor: Any, row: Appointment, schedule: Schedule) -> None:
    """The appointment in the schedule's calendar: kind and code only, never the patient.

    A walk-in appointment has no event of its own: its session has one.
    """
    from . import calendar_bridge

    if row.mode == WALK_IN:
        _project_session(actor, schedule, row.starts_at)
        return
    attendees = ()
    if row.professional_id is not None:
        user = Professional.objects.filter(pk=row.professional_id).values_list("user_id", flat=True).first()
        attendees = (user,) if user else ()
    calendar_bridge.put_event(
        actor,
        source_key=str(row.pk),
        calendar_id=schedule.calendar_id,
        title=f"{row.appointment_type.name} · {row.code}",
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        tzid=schedule.practice.timezone,
        attendee_user_ids=attendees,
        path=calendar_bridge.source_path(schedule.pk, row.pk),
    )


def _readable_patient(actor: Any, patient_id: object) -> Any:
    from applications.med_patients.service_api import PatientService

    summary = PatientService().summary(actor=actor, patient_id=as_uuid(patient_id, field="patient_id"))
    if summary.status != "active":
        raise Conflict("patient_inactive", gettext("O paciente não está ativo."))
    if summary.processing_restricted:
        raise Conflict("processing_restricted", gettext("O tratamento dos dados deste paciente está restrito."))
    return summary


def _book(
    actor: Any,
    *,
    schedule_id: object,
    patient_id: object,
    appointment_type_id: object,
    starts_at: object,
    duration_minutes: object,
    fit_in: object,
    notes: object,
    payment_kind: object,
    room_id: object,
    idempotency_key: object,
    rescheduled_from: Appointment | None = None,
    mode: object = "booked",
) -> Appointment:
    """Book an appointment (the body of ``SchedulingService.book``, shared with a reschedule)."""
    from datetime import timedelta

    from skeleton.access.policies import require_parent_action
    from skeleton.service_api.sequences import SequenceService

    from .registration import APPOINTMENT_SEQUENCE

    key = common.key(idempotency_key)
    starts_at = _aware(starts_at, "starts_at")
    mode = _check_mode(mode)
    if payment_kind is not None and payment_kind not in PaymentKind.values:
        raise InvalidInput({"payment_kind": [gettext("Forma de pagamento desconhecida.")]})
    if len(str(notes)) > 2000:
        raise InvalidInput({"notes": [gettext("Texto longo demais.")]})
    if duration_minutes is not None and (type(duration_minutes) is not int or not 5 <= duration_minutes <= 480):
        raise InvalidInput({"duration_minutes": [gettext("Use de 5 a 480 minutos.")]})
    sysid = common.deterministic_id("appointment", actor, key)
    existing = Appointment.objects.filter(pk=sysid).first()
    if existing is not None:
        return existing
    schedule = _schedule(actor, schedule_id, write=True, lock=True)
    require_parent_action(Appointment, schedule, user=actor, action="create")
    patient = _readable_patient(actor, patient_id)
    kind = common.row(actor, AppointmentType, appointment_type_id, field="appointment_type_id", write=False)
    own_duration = _type_duration(actor, schedule, kind, mode=mode)
    if own_duration is None:
        raise _type_not_taken(mode)
    room = common.row(actor, Room, room_id, field="room_id", write=False) if room_id is not None else schedule.room
    if kind.requires_room and room is None:
        raise InvalidInput({"room_id": [gettext("Este tipo de atendimento exige uma sala.")]})
    planned = duration_minutes or own_duration
    if mode == WALK_IN:
        # No time of its own: the appointment takes the bounds of the walk-in period that holds the instant.
        period = _session_for(actor, schedule, starts_at)
        _check_session(actor, schedule, kind, period, planned, fit_in=bool(fit_in), room=room)
        starts_at, ends_at = period.starts_at, period.ends_at
    else:
        ends_at = starts_at + timedelta(minutes=planned)
        _check_interval(actor, schedule, kind, starts_at, ends_at, fit_in=bool(fit_in), room=room)
    number = SequenceService().next_number(actor=actor, key=APPOINTMENT_SEQUENCE)
    row = Appointment(
        sysid=sysid,
        organization_id=schedule.organization_id,
        schedule=schedule,
        code=number.formatted,
        patient_id=patient.sysid,
        appointment_type=kind,
        professional_id=schedule.professional_id,
        room=room,
        starts_at=starts_at,
        ends_at=ends_at,
        is_fit_in=bool(fit_in),
        billing_code=kind.billing_code,
        payment_kind=str(kind.payment_kind if payment_kind is None else payment_kind),
        notes=str(notes).strip(),
        rescheduled_from=rescheduled_from,
        mode=mode,
        duration_minutes=planned,
    )
    row.save()
    _project(actor, row, schedule)
    _publish(actor, "booked", row)
    return row


def _check_interval(
    actor: Any,
    schedule: Schedule,
    kind: AppointmentType,
    starts_at: datetime,
    ends_at: datetime,
    *,
    fit_in: bool,
    room: Room | None,
    ignore: UUID | None = None,
) -> None:
    """The rules of a booking with a time: in the grid of booked time and free (unless a fit-in), never over a block.

    A time inside a walk-in period is refused as ``mode_mismatch``: there the booking has no time.
    """
    from . import plan
    from .slots import fits_grid
    from .transitions import LIVE

    if _blocked(actor, schedule, starts_at, ends_at):
        raise Conflict("slot_unavailable", gettext("O horário está bloqueado."))
    if not fit_in:
        windows = _schedule_windows(actor, schedule)
        timezone = schedule.practice.timezone
        if not fits_grid(windows, starts_at, ends_at, timezone=timezone, appointment_type_id=kind.pk):
            periods = plan.periods_on(windows, plan.local_day(starts_at, timezone), timezone)
            if any(
                period.mode == WALK_IN and period.starts_at < ends_at and starts_at < period.ends_at
                for period in periods
            ):
                raise Conflict(
                    "mode_mismatch",
                    gettext("Este período atende por ordem de chegada: marque sem hora, ou como encaixe."),
                )
            raise Conflict("slot_unavailable", gettext("O horário está fora da grade da agenda."))
        live = Appointment.objects.filter(
            schedule=schedule, status__in=LIVE, starts_at__lt=ends_at, ends_at__gt=starts_at
        )
        if ignore is not None:
            live = live.exclude(pk=ignore)
        if live.exists():
            raise Conflict("slot_unavailable", gettext("Já existe consulta neste horário."))
    if room is not None:
        # The walk-in appointments of this schedule share their period: they take the room as one.
        busy_room = Appointment.objects.filter(
            room=room, status__in=LIVE, starts_at__lt=ends_at, ends_at__gt=starts_at
        ).exclude(schedule=schedule, mode=WALK_IN)
        if ignore is not None:
            busy_room = busy_room.exclude(pk=ignore)
        if busy_room.exists():
            raise Conflict("room_unavailable", gettext("A sala já está ocupada neste horário."))


def _type_not_taken(mode: str) -> Conflict:
    if mode == WALK_IN:
        return Conflict(
            "type_not_allowed", gettext("Esta agenda não atende este tipo de atendimento por ordem de chegada.")
        )
    return Conflict("type_not_allowed", gettext("Esta agenda não atende este tipo de atendimento."))


# The shortest appointment: a session with less room than this is full.
MIN_DURATION = 5


def _session_for(actor: Any, schedule: Schedule, moment: datetime) -> Any:
    """The walk-in period of the schedule that holds the instant (``plan.Period``)."""
    from . import plan

    timezone = schedule.practice.timezone
    periods = plan.periods_on(_schedule_windows(actor, schedule), plan.local_day(moment, timezone), timezone)
    found = plan.period_at(periods, moment, WALK_IN)
    if found is None:
        if plan.period_at(periods, moment) is not None:
            raise Conflict("mode_mismatch", gettext("Este período atende com hora marcada: escolha um horário."))
        raise Conflict("slot_unavailable", gettext("Não há período de ordem de chegada neste horário."))
    return found


def _check_session(
    actor: Any,
    schedule: Schedule,
    kind: AppointmentType,
    period: Any,
    planned: int,
    *,
    fit_in: bool,
    room: Room | None,
    ignore: UUID | None = None,
) -> None:
    """The rules of a walk-in booking: a period some block leaves open, of the kind and with room (unless a fit-in).

    The room of the session is its capacity, or its open minutes against the planned durations.
    The appointments of the session share the interval, so they never dispute the schedule's room
    with each other, only with other schedules.
    """
    from . import plan
    from .transitions import CANCELLED, LIVE

    blocked = _blocked(actor, schedule, period.starts_at, period.ends_at)
    if plan.open_minutes(period, blocked) <= 0:
        raise Conflict("slot_unavailable", gettext("O período está bloqueado."))
    if not fit_in:
        if period.kinds and kind.pk not in period.kinds:
            raise Conflict("type_not_allowed", gettext("Este período não atende este tipo de atendimento."))
        rows = Appointment.objects.filter(
            schedule=schedule, mode=WALK_IN, starts_at=period.starts_at, is_fit_in=False
        ).exclude(status=CANCELLED)
        if ignore is not None:
            rows = rows.exclude(pk=ignore)
        taken = [_planned(row) for row in rows.only("duration_minutes", "starts_at", "ends_at")]
        if plan.is_full(period, taken, planned, blocked=blocked):
            raise Conflict("session_full", gettext("O período de ordem de chegada está lotado."))
    if room is not None:
        busy_room = Appointment.objects.filter(
            room=room, status__in=LIVE, starts_at__lt=period.ends_at, ends_at__gt=period.starts_at
        ).exclude(schedule=schedule)
        if busy_room.exists():
            raise Conflict("room_unavailable", gettext("A sala já está ocupada neste horário."))


def _locked(actor: Any, appointment_id: object, expected_revision: object) -> tuple[Schedule, Appointment]:
    """The schedule and then the appointment, locked in the order every operation uses, with CAS."""
    # Read without a lock only to learn the schedule, which never changes.
    seen = _appointment(actor, appointment_id, write=True)
    schedule = _schedule(actor, seen.schedule_id, write=True, lock=True)
    row = _appointment(actor, appointment_id, write=True, lock=True)
    common.check_revision(row, expected_revision)
    return schedule, row


def _sessions(
    schedule_id: UUID, day: date, periods: Any, rows: Any, blocked: list[tuple[datetime, datetime]]
) -> tuple[QueueSession, ...]:
    """The walk-in sessions of a schedule on a day, from its periods and the appointments already read.

    A session whose period left the grid since still shows, by the bounds its appointments keep.
    """
    from . import plan, queue
    from .transitions import ARRIVED, CANCELLED, COMPLETED, CONFIRMED, IN_PROGRESS, NO_SHOW, SCHEDULED

    booked: dict[datetime, list[Appointment]] = {}
    for row in rows:
        if row.mode == WALK_IN:
            booked.setdefault(row.starts_at, []).append(row)
    bounds = {period.starts_at: period for period in periods if period.mode == WALK_IN}
    for start, found in booked.items():
        bounds.setdefault(start, plan.Period(day, 0, 0, start, found[0].ends_at, WALK_IN))

    def entry(row: Appointment, position: int | None = None) -> QueueEntry:
        return QueueEntry(
            appointment_info(row), as_utc(row.arrived_at) if row.arrived_at else None, row.is_priority, position
        )

    result = []
    for start in sorted(bounds):
        period = bounds[start]
        found = sorted(booked.get(start, []), key=lambda row: (row.code, str(row.pk)))  # The order they were booked.
        counted = [_planned(row) for row in found if row.status != CANCELLED and not row.is_fit_in]
        waiting = queue.call_order(row for row in found if row.status == ARRIVED)
        result.append(
            QueueSession(
                schedule_id,
                day,
                as_utc(period.starts_at),
                as_utc(period.ends_at),
                period.capacity,
                len(counted),
                sum(counted),
                plan.open_minutes(period, blocked),
                plan.is_full(period, counted, MIN_DURATION, blocked=blocked),
                tuple(entry(row, position) for position, row in enumerate(waiting, start=1)),
                tuple(entry(row) for row in found if row.status in (SCHEDULED, CONFIRMED)),
                tuple(entry(row) for row in found if row.status == IN_PROGRESS),
                tuple(entry(row) for row in found if row.status in (COMPLETED, NO_SHOW)),
            )
        )
    return tuple(result)


def _transition(
    actor: Any, appointment_id: object, expected_revision: object, action: str, *, extra: Any = None
) -> Appointment:
    """Apply one transition of ``transitions.py`` with CAS, stamp its time and publish its event.

    ``extra(schedule, row)`` gives more values to save with the state; it runs once the transition
    is known to be allowed, with the schedule locked before the appointment.
    """
    from django.utils import timezone

    from . import transitions

    schedule = None
    if extra is None:
        row = _appointment(actor, appointment_id, write=True, lock=True)
        common.check_revision(row, expected_revision)
    else:
        schedule, row = _locked(actor, appointment_id, expected_revision)
    try:
        state = transitions.target(action, row.status)
    except transitions.InvalidTransition:
        raise Conflict("invalid_transition", gettext("Esta mudança de situação não é permitida agora.")) from None
    now = timezone.now()
    if action == "mark_no_show":
        if row.mode == WALK_IN and now < row.ends_at:
            raise Conflict("invalid_transition", gettext("Só é possível marcar falta depois do fim do período."))
        if now < row.starts_at:
            raise Conflict("invalid_transition", gettext("Só é possível marcar falta depois do horário da consulta."))
    values: dict[str, Any] = {"status": state}
    stamp = transitions.STAMP_OF.get(action)
    if stamp is not None:
        values[stamp] = now
    if extra is not None:
        values.update(extra(schedule, row))
    common.apply_changes(row, values)
    _publish(actor, transitions.EVENT_OF[action], row)
    return row


def _notify_arrival(actor: Any, row: Appointment) -> None:
    from skeleton.service_api.notifications import NotificationService, Recipients

    from .registration import ARRIVAL_NOTIFICATION

    if row.professional_id is None:
        return
    person = Professional.objects.filter(pk=row.professional_id).values_list("user_id", flat=True).first()
    if person is None:
        return
    NotificationService().notify(
        actor=actor,
        type_code=ARRIVAL_NOTIFICATION,
        recipients=Recipients(users=(person,)),
        payload=(("code", row.code), ("starts_at", as_utc(row.starts_at).isoformat())),
        target_table_key="med_scheduling.appointment",
        target_id=row.pk,
        dedupe_key=f"arrived:{row.pk}",
    )


PERIODS = {"morning": (0, 12 * 60), "afternoon": (12 * 60, 18 * 60), "evening": (18 * 60, 24 * 60), "any": (0, 24 * 60)}


def _priority_first() -> Any:
    """High priority first: an explicit order (the codes do not sort by importance)."""
    from django.db.models import Case, IntegerField, Value, When

    return Case(When(priority="high", then=Value(0)), default=Value(1), output_field=IntegerField())


def _put_rules(
    actor: Any,
    schedule: Schedule,
    wanted: list[tuple[AvailabilityRuleInput, frozenset[UUID]]],
    rows: Any,
    on_date: date | None = None,
) -> None:
    """Make ``rows`` (the weekly grid of a schedule, or the exception of ``on_date``) be the windows ``wanted``.

    A window that stays (same weekday, minutes and validity) keeps its row and only what changed
    in it is written; the others are created, and the rows no window wants are deleted, their
    kinds first.
    """
    from skeleton.access.policies import authorized_queryset

    existing: dict[Any, AvailabilityRule] = {}
    leaving: list[AvailabilityRule] = []
    for row in rows:
        # Two live rows of the same window should not exist; if they do, one stays.
        if _shape(row) in existing:
            leaving.append(row)
        else:
            existing[_shape(row)] = row
    links: dict[UUID, dict[UUID, AvailabilityRuleType]] = {}
    for link in authorized_queryset(AvailabilityRuleType, user=actor, action="delete").filter(
        rule_id__in=[row.pk for row in (*existing.values(), *leaving)]
    ):
        links.setdefault(link.rule_id, {})[link.appointment_type_id] = link
    types = _schedule_types(actor, schedule)
    taken = {
        BOOKED: {item.appointment_type_id for item in types if item.allow_booked},
        WALK_IN: {item.appointment_type_id for item in types if item.allow_walk_in},
    }

    def refuse_unknown(kinds: frozenset[UUID], mode: str) -> None:
        if kinds - taken[mode]:
            raise InvalidInput(
                {
                    "appointment_type_ids": [
                        gettext(
                            "O período lista um tipo de atendimento desconhecido, inativo ou que a agenda"
                            " não atende neste modo."
                        )
                    ]
                }
            )

    for rule, kinds in wanted:
        row = existing.pop(_shape(rule), None)
        current: dict[UUID, AvailabilityRuleType] = {}
        if row is None:
            refuse_unknown(kinds, rule.mode)
            row = AvailabilityRule(
                organization_id=schedule.organization_id,
                schedule=schedule,
                weekday=rule.weekday,
                start_minute=rule.start_minute,
                end_minute=rule.end_minute,
                valid_from=rule.valid_from,
                valid_until=rule.valid_until,
                mode=rule.mode,
                capacity=rule.capacity,
                on_date=on_date,
            )
            row.save()
        else:
            current = links.get(row.pk, {})
            had = frozenset(_kinds_of_rule(row, current))
            same_mode = row.mode == rule.mode
            if had == kinds and same_mode and row.capacity == rule.capacity:
                continue
            # While the mode stays only what comes in is checked: a kind the window already had
            # may have left the schedule since.
            refuse_unknown(kinds - had if same_mode else kinds, rule.mode)
            # The single kind of an older row moves to the link rows with the others.
            common.apply_changes(row, {"mode": rule.mode, "capacity": rule.capacity, "appointment_type_id": None})
        for type_id, link in current.items():
            if type_id not in kinds:
                link.delete()
        for type_id in sorted(kinds - set(current), key=str):
            AvailabilityRuleType(organization_id=schedule.organization_id, rule=row, appointment_type_id=type_id).save()
    for row in (*existing.values(), *leaving):
        # The links first: the way from a link to the schedule goes through a live window.
        for link in links.get(row.pk, {}).values():
            link.delete()
        row.delete()


MAX_DAY_WINDOWS = 20


def _exception_windows(actor: Any, schedule: Schedule, day: date) -> list[AvailabilityRuleInfo]:
    """The periods of the exception of a day, by start."""
    from skeleton.access.policies import authorized_queryset

    rows = list(
        authorized_queryset(AvailabilityRule, user=actor, action="read")
        .filter(schedule=schedule, on_date=day)
        .order_by("start_minute", "sysid")
    )
    kinds = _rule_kinds(actor, rows)
    return [rule_info(row, kinds.get(row.pk, ())) for row in rows]


# The moves a change of plan makes once the owner confirms them (``plan.TO_WALK_IN``, ``plan.TO_SESSION``).
MOVES = ("to_walk_in", "to_session")


def _check_day(schedule: Schedule, day: object, *, past: bool = False) -> date:
    """A local day of the practice; one already over is refused unless ``past`` takes it."""
    from django.utils import timezone as dj_timezone

    from . import plan

    if type(day) is not date:
        raise InvalidInput({"date": [gettext("Informe uma data.")]})
    if not past and day < plan.local_day(dj_timezone.now(), schedule.practice.timezone):
        raise InvalidInput({"date": [gettext("Este dia já passou.")]})
    return day


def _check_day_windows(windows: object, day: date) -> list[tuple[AvailabilityRuleInput, frozenset[UUID]]]:
    """The periods asked for a day, as windows of that day only: at least one, well formed, not overlapping."""
    if (
        not isinstance(windows, tuple)
        or not 1 <= len(windows) <= MAX_DAY_WINDOWS
        or not all(isinstance(window, DayWindowInput) for window in windows)
    ):
        raise InvalidInput(
            {"windows": [gettext("Informe de 1 a 20 períodos (DayWindowInput). Para fechar o dia, use um bloqueio.")]}
        )
    asked = tuple(
        AvailabilityRuleInput(
            day.weekday(),
            window.start_minute,
            window.end_minute,
            day,
            day,
            None,
            window.appointment_type_ids,
            window.mode,
            window.capacity,
        )
        for window in windows
    )
    try:
        return _check_rules(asked)
    except InvalidInput as error:
        if "rules" in error.errors:
            raise InvalidInput({"windows": [gettext("Dois períodos do dia se sobrepõem.")]}) from None
        raise


def _day_windows(wanted: list[tuple[AvailabilityRuleInput, frozenset[UUID]]], day: date | None) -> list[Any]:
    """The windows asked for as the pure functions take them; of the exception of ``day`` when given."""
    from .slots import Window

    return [
        Window(
            rule.weekday,
            rule.start_minute,
            rule.end_minute,
            rule.valid_from,
            rule.valid_until,
            None,
            kinds,
            rule.mode,
            rule.capacity,
            day,
        )
        for rule, kinds in wanted
    ]


def _plan_rows(queryset: Any, schedule: Schedule, since: datetime, until: datetime | None = None) -> list[Appointment]:
    """The appointments a change of plan looks at, among those that start from ``since`` (before ``until``).

    They are the ones that still follow the grid (scheduled, confirmed or arrived) and whoever
    holds an arrival number, whose session must stay as it is. A fit-in with a time never
    followed the grid, and an appointment with a time being attended or over is not touched.
    """
    from django.db.models import Q

    from .transitions import ARRIVED, CANCELLED, CONFIRMED, SCHEDULED

    rows = queryset.filter(schedule=schedule, starts_at__gte=since)
    if until is not None:
        rows = rows.filter(starts_at__lt=until)
    rows = (
        rows.filter(Q(status__in=(SCHEDULED, CONFIRMED, ARRIVED)) | Q(mode=WALK_IN, arrival_number__isnull=False))
        .exclude(status=CANCELLED)
        .exclude(mode=BOOKED, is_fit_in=True)
    )
    return list(rows.order_by("starts_at", "code", "sysid"))


def _plan_changes(
    schedule: Schedule, rows: list[Appointment], current: list[Any], wanted: list[Any]
) -> list[tuple[Appointment, str, Any]]:
    """What the windows ``wanted`` do to ``rows`` that the ``current`` ones do not: ``(row, reason, period)``.

    An appointment the current plan already fails to hold for the same reason is not a change.
    """
    from . import plan
    from .transitions import ARRIVED

    timezone = schedule.practice.timezone
    by_day: dict[date, list[Appointment]] = {}
    for row in rows:
        by_day.setdefault(plan.local_day(row.starts_at, timezone), []).append(row)
    found = []
    for day in sorted(by_day):
        known = {row.pk: row for row in by_day[day]}
        bookings = [
            plan.Booking(
                row.pk,
                str(row.mode),
                row.starts_at,
                row.ends_at,
                row.status == ARRIVED or row.arrival_number is not None,
            )
            for row in by_day[day]
        ]
        already = {
            (booking.key, reason)
            for booking, reason, _period in plan.conflicts(plan.periods_on(current, day, timezone), bookings)
        }
        for booking, reason, period in plan.conflicts(plan.periods_on(wanted, day, timezone), bookings):
            if (booking.key, reason) not in already:
                found.append((known[booking.key], reason, period))
    return found


def _plan_conflicts(
    actor: Any, schedule: Schedule, changes: list[tuple[Appointment, str, Any]], rows: list[Appointment]
) -> tuple[PlanConflict, ...]:
    """The changes as the confirmation shows them, with what a move ignores: the room of the session and its kinds."""
    from . import plan

    moving = {row.pk for row, reason, _period in changes if reason in MOVES}
    over: dict[datetime, bool] = {}
    result = []
    for row, reason, period in changes:
        crowded = unlisted = False
        if reason in MOVES:
            unlisted = bool(period.kinds) and row.appointment_type_id not in period.kinds
            if period.starts_at not in over:
                planned = [
                    _planned(other)
                    for other in rows
                    if other.mode == WALK_IN
                    and other.pk not in moving
                    and not other.is_fit_in
                    and (other.starts_at, other.ends_at) == (period.starts_at, period.ends_at)
                ]
                planned += [
                    _planned(other)
                    for other, why, target in changes
                    if why in MOVES and target.starts_at == period.starts_at and not other.is_fit_in
                ]
                if period.capacity is not None:
                    over[period.starts_at] = len(planned) > period.capacity
                else:
                    blocked = _blocked(actor, schedule, period.starts_at, period.ends_at)
                    over[period.starts_at] = sum(planned) > plan.open_minutes(period, blocked)
            crowded = over[period.starts_at] and not row.is_fit_in
        result.append(
            PlanConflict(
                appointment_info(row),
                reason,
                reason in plan.BLOCKING,
                as_utc(period.starts_at) if period is not None else None,
                as_utc(period.ends_at) if period is not None else None,
                crowded,
                unlisted,
            )
        )
    return tuple(result)


def _replan_day(
    actor: Any,
    schedule: Schedule,
    day: date,
    wanted: list[Any],
    convert_existing: object,
    expected_affected: object,
) -> list[tuple[Appointment, Any]]:
    """Check what the windows ``wanted`` for ``day`` do to its appointments; the moves to make come back.

    The schedule is locked, so nobody books meanwhile; the rows are locked after it. The list the
    owner confirmed (``expected_affected``) has to be the one found now: booking an appointment
    does not change the revision of the schedule, so the CAS alone does not protect it.
    """
    from . import plan

    convert = _check_flag(convert_existing, "convert_existing")
    start, end = _day_window(day, day, schedule.practice.timezone)
    rows = _plan_rows(Appointment.objects.select_for_update(), schedule, start, end)
    changes = _plan_changes(schedule, rows, _schedule_windows(actor, schedule), wanted)
    if any(reason in plan.BLOCKING for _row, reason, _period in changes):
        raise Conflict(
            "plan_conflicts",
            gettext("Há consultas neste dia que a mudança não comporta. Remarque-as ou ajuste os períodos."),
        )
    moves = [(row, period) for row, _reason, period in changes]
    if not convert:
        if moves:
            raise Conflict(
                "plan_conflicts",
                gettext("A mudança leva consultas já marcadas para a ordem de chegada. Confira a lista e confirme."),
            )
        return []
    if not isinstance(expected_affected, tuple):
        raise InvalidInput({"expected_affected": [gettext("Informe as consultas conferidas numa tupla.")]})
    expected = {as_uuid(value, field="expected_affected") for value in expected_affected}
    if expected != {row.pk for row, _period in moves}:
        raise Conflict(
            "plan_changed",
            gettext("As consultas deste dia mudaram desde a conferência. Confira a lista de novo."),
        )
    return moves


def _move_to_sessions(actor: Any, schedule: Schedule, moves: list[tuple[Appointment, Any]]) -> None:
    """Take each appointment to the walk-in session of its new period: the same code, no time of its own.

    A confirmed one goes back to scheduled, as in a reschedule. The limits of the session (its
    capacity, the kinds of its period) are not checked: the owner saw them in the confirmation.
    """
    from . import calendar_bridge
    from .transitions import CONFIRMED, SCHEDULED

    touched: set[datetime] = set()
    for row, period in moves:
        left = (str(row.mode), row.starts_at)
        values: dict[str, Any] = {
            "starts_at": period.starts_at,
            "ends_at": period.ends_at,
            "mode": WALK_IN,
            "duration_minutes": _planned(row),
            "arrival_number": None,
        }
        if row.status == CONFIRMED:
            values["status"] = SCHEDULED
        common.apply_changes(row, values)
        if left[0] == WALK_IN:
            touched.add(left[1])
        else:
            calendar_bridge.remove_event(actor, source_key=str(row.pk))
        touched.add(period.starts_at)
        _publish(actor, "rescheduled", row)
    for starts_at in sorted(touched):
        _project_session(actor, schedule, starts_at)


def _grid_changes(
    actor: Any, schedule: Schedule, wanted: list[tuple[AvailabilityRuleInput, frozenset[UUID]]], queryset: Any
) -> list[tuple[Appointment, str, Any]]:
    """The appointments from today on that a new weekly grid would leave in a period of the other mode.

    The days with an exception keep following it, so nothing changes on them.
    """
    from django.utils import timezone as dj_timezone

    from . import plan

    timezone = schedule.practice.timezone
    today = plan.local_day(dj_timezone.now(), timezone)
    rows = _plan_rows(queryset, schedule, _day_window(today, today, timezone)[0])
    if not rows:
        return []
    current = _schedule_windows(actor, schedule)
    grid = _day_windows(wanted, None) + [window for window in current if window.on_date is not None]
    return [
        (row, reason, period)
        for row, reason, period in _plan_changes(schedule, rows, current, grid)
        if reason in (plan.TO_WALK_IN, plan.TO_BOOKED) or (reason == plan.ARRIVED and row.mode == BOOKED)
    ]


def _refuse_mode_conflicts(
    actor: Any, schedule: Schedule, wanted: list[tuple[AvailabilityRuleInput, frozenset[UUID]]]
) -> None:
    """Refuse a weekly grid that changes the mode of a period under appointments already booked."""
    from . import plan

    clash = _grid_changes(actor, schedule, wanted, Appointment.objects)
    if clash:
        last = max(plan.local_day(row.starts_at, schedule.practice.timezone) for row, _reason, _period in clash)
        raise Conflict(
            "plan_conflicts",
            gettext(
                "A grade nova troca o modo de períodos que têm consultas marcadas até %(day)s. Faça a mudança"
                " valer depois desse dia, ou altere um dia de cada vez."
            )
            % {"day": f"{last:%d/%m/%Y}"},
        )


def _fits_period(period: str, starts_at: datetime, timezone: str) -> bool:
    from zoneinfo import ZoneInfo

    local = starts_at.astimezone(ZoneInfo(timezone))
    minute = local.hour * 60 + local.minute
    start, end = PERIODS.get(period, PERIODS["any"])
    return start <= minute < end


# ------------------------------------------------------------------------------------ service


class SchedulingService(ServiceAPI):
    """The clinic's agenda: practice, professionals, rooms, schedules, appointments and the waitlist."""

    app_label = APP_LABEL

    # ------------------------------------------------------------------ practice

    @service_method(read_only=False, since="0.1.0")
    def setup(
        self,
        *,
        actor: Any,
        practice_name: str,
        timezone: str = "America/Sao_Paulo",
        reader_group_ids: tuple[UUID, ...] = (),
        manager_group_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> PracticeInfo:
        """Create the default practice of the organization and share it with groups.

        Autorização: a capacidade ``access.manage`` e ``create`` em med_scheduling.practice.
        Erros: Forbidden; InvalidInput para nome vazio, fuso desconhecido, chave inválida ou mais
        de 20 grupos; Conflict("already_set_up") com um consultório padrão criado por outra chave.
        Efeitos: cria o consultório (privado, dono o ator), dá ao papel ``member`` leitura das
        tabelas do consultório e das agendas, concede leitura aos grupos de leitura e leitura e
        alteração aos de gestão. A mesma chave do mesmo ator devolve o já criado.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.access import AccessService
        from skeleton.tenancy.context import current_context

        from .services import clean_practice

        key = common.key(idempotency_key)
        managers = common.group_ids(manager_group_ids, "manager_group_ids")
        readers = tuple(
            group for group in common.group_ids(reader_group_ids, "reader_group_ids") if group not in managers
        )
        values = clean_practice({"name": practice_name, "timezone": timezone}, partial=False)
        common.require_access_manager(actor)
        if not has_table_permission(Practice, user=actor, action="create"):
            raise Forbidden()
        sysid = common.deterministic_id("practice", actor, key)
        existing = Practice.objects.filter(pk=sysid).first()
        if existing is not None:
            return practice_info(existing, writable=True)
        if Practice.objects.filter(is_default=True).exists():
            raise Conflict("already_set_up")
        practice = Practice(
            sysid=sysid,
            organization_id=current_context().organization_id,
            owner_id=actor.pk,
            visibility=Practice.Visibility.PRIVATE,
            is_default=True,
            **values,
        )
        practice.save()
        access = AccessService()
        for table in MEMBER_TABLES:
            access.grant_member_table_access(actor=actor, table_key=table, actions=("read", "update"))
        for group in readers + managers:
            access.grant_record_access(
                actor=actor, table_key=PRACTICE_TABLE, record_id=practice.pk, action="read", group_id=group
            )
        for group in managers:
            access.grant_record_access(
                actor=actor, table_key=PRACTICE_TABLE, record_id=practice.pk, action="update", group_id=group
            )
        return practice_info(practice, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def practice(self, *, actor: Any) -> PracticeInfo:
        """The default practice of the organization.

        Autorização: leitura do consultório.
        Erros: NotFound sem consultório configurado ou sem leitura.
        Efeitos: nenhum.
        """
        practice = _practice(actor)
        return practice_info(practice, writable=_practice_writable(actor, practice))

    @service_method(read_only=False, since="0.1.0")
    def update_practice(
        self, *, actor: Any, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> PracticeInfo:
        """Change the establishment data or the time zone of the practice, with CAS.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram.
        """
        from .services import PRACTICE_FIELDS, clean_practice

        values = common.changes_dict(changes)
        common.refuse_unknown(values, PRACTICE_FIELDS)
        clean = clean_practice(values, partial=True)
        practice = _practice(actor, write=True, lock=True)
        common.check_revision(practice, expected_revision)
        common.apply_changes(practice, clean)
        return practice_info(practice, writable=True)

    # ------------------------------------------------------------------ professionals

    @service_method(read_only=True, since="0.1.0")
    def professionals(self, *, actor: Any, active_only: bool = True) -> tuple[ProfessionalInfo, ...]:
        """Professionals of the practice, by name.

        Autorização: leitura do consultório.
        Erros: NotFound sem consultório legível.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        practice = _practice(actor)
        rows = authorized_queryset(Professional, user=actor, action="read").filter(practice=practice)
        if active_only:
            rows = rows.filter(is_active=True)
        return tuple(professional_info(row) for row in rows.order_by("display_name", "sysid")[:500])

    @service_method(read_only=True, since="0.1.0")
    def professional(self, *, actor: Any, professional_id: UUID) -> ProfessionalInfo:
        """One professional.

        Autorização: leitura do consultório.
        Erros: NotFound para profissional inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        return professional_info(common.row(actor, Professional, professional_id, field="professional_id", write=False))

    @service_method(read_only=True, since="0.1.0")
    def my_professional(self, *, actor: Any) -> ProfessionalInfo | None:
        """The active professional record linked to the actor, or ``None``.

        Autorização: leitura do consultório.
        Erros: nenhum além do contrato; sem consultório legível, ``None``.
        Efeitos: nenhum.
        """
        from django.core.exceptions import PermissionDenied

        from skeleton.access.policies import authorized_queryset

        try:
            row = (
                authorized_queryset(Professional, user=actor, action="read")
                .filter(user_id=actor.pk, is_active=True)
                .order_by("created_at")
                .first()
            )
        except PermissionDenied:
            return None
        return professional_info(row) if row is not None else None

    @service_method(read_only=False, since="0.1.0")
    def register_professional(
        self,
        *,
        actor: Any,
        display_name: str,
        council: str = "crm",
        council_number: str = "",
        council_state: str = "",
        specialty: str = "",
        rqe: str = "",
        tax_id: str = "",
        membership_user_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> ProfessionalInfo:
        """Register a professional of the practice, optionally linked to a member of the organization.

        Autorização: alteração no consultório.
        Erros: NotFound sem consultório; Forbidden se só lê; InvalidInput com o nome do campo ou
        para pessoa que não é membro ativo; Conflict("integrity_conflict") para pessoa já ligada a
        outro profissional vivo; Conflict("quota_exceeded") acima do limite de profissionais do plano.
        Efeitos: grava o profissional; a mesma chave do mesmo ator devolve o já criado.
        """
        from skeleton.service_api.organizations import OrganizationService

        from .services import clean_professional

        values = clean_professional(
            {
                "display_name": display_name,
                "council": council,
                "council_number": council_number,
                "council_state": council_state,
                "specialty": specialty,
                "rqe": rqe,
                "tax_id": tax_id,
            },
            partial=False,
        )
        practice = _practice(actor, write=True)
        row = _new_child(actor, Professional, practice, idempotency_key, "professional")
        if idempotency_key is not None:
            existing = Professional.objects.filter(pk=row.sysid).first()
            if existing is not None:
                return professional_info(existing)
        if membership_user_id is not None:
            user = as_uuid(membership_user_id, field="membership_user_id")
            if not OrganizationService().is_member(actor=actor, user_id=user):
                raise InvalidInput(
                    {"membership_user_id": [gettext("A pessoa precisa ser membro ativo da organização.")]}
                )
            row.user_id = user
        for name, value in values.items():
            setattr(row, name, value)
        self._check_quota(actor)
        row.save()
        return professional_info(row)

    def _check_quota(self, actor: Any) -> None:
        """One more active professional must fit the plan (``med_scheduling.active_professionals``).

        With the platform billing off (the default) or a plan without that limit, nothing is refused;
        above the limit the core's ``Conflict("quota_exceeded")`` passes through untranslated.
        """
        from skeleton.service_api.billing import BillingService

        BillingService().check_quota(actor=actor, metric=QUOTA_ACTIVE_PROFESSIONALS, increment=1)

    @service_method(read_only=False, since="0.1.0")
    def update_professional(
        self, *, actor: Any, professional_id: UUID, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> ProfessionalInfo:
        """Change the data of a professional, with CAS; the linked person never changes.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram.
        """
        from .services import PROFESSIONAL_FIELDS, clean_professional

        values = common.changes_dict(changes)
        common.refuse_unknown(values, PROFESSIONAL_FIELDS)
        clean = clean_professional(values, partial=True)
        row = common.row(actor, Professional, professional_id, field="professional_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        common.apply_changes(row, clean)
        return professional_info(row)

    @service_method(read_only=False, since="0.1.0")
    def set_professional_active(
        self, *, actor: Any, professional_id: UUID, active: bool, expected_revision: int
    ) -> ProfessionalInfo:
        """Deactivate (or reactivate) a professional, with CAS.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; Conflict("stale_revision"); Conflict("quota_exceeded") ao
        reativar acima do limite de profissionais do plano.
        Efeitos: grava a situação; um profissional inativo some das listas e não recebe agenda nova.
        """
        row = common.row(actor, Professional, professional_id, field="professional_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        if active and not row.is_active:
            self._check_quota(actor)
        common.apply_changes(row, {"is_active": bool(active)})
        return professional_info(row)

    # ------------------------------------------------------------------ rooms and appointment types

    @service_method(read_only=True, since="0.1.0")
    def rooms(self, *, actor: Any, active_only: bool = True) -> tuple[RoomInfo, ...]:
        """Rooms and equipment of the practice.

        Autorização: leitura do consultório.
        Erros: NotFound sem consultório legível.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        practice = _practice(actor)
        rows = authorized_queryset(Room, user=actor, action="read").filter(practice=practice)
        if active_only:
            rows = rows.filter(is_active=True)
        return tuple(room_info(row) for row in rows.order_by("name", "sysid")[:200])

    @service_method(read_only=False, since="0.1.0")
    def add_room(self, *, actor: Any, name: str, kind: str = "room", idempotency_key: str | None = None) -> RoomInfo:
        """Add a room or a piece of equipment.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput.
        Efeitos: grava a sala; a mesma chave do mesmo ator devolve a já criada.
        """
        from .services import clean_room

        values = clean_room({"name": name, "kind": kind}, partial=False)
        practice = _practice(actor, write=True)
        row = _new_child(actor, Room, practice, idempotency_key, "room")
        existing = Room.objects.filter(pk=row.sysid).first() if idempotency_key is not None else None
        if existing is not None:
            return room_info(existing)
        for field, value in values.items():
            setattr(row, field, value)
        row.save()
        return room_info(row)

    @service_method(read_only=False, since="0.1.0")
    def update_room(
        self, *, actor: Any, room_id: UUID, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> RoomInfo:
        """Rename, change the kind or (de)activate a room, with CAS.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram.
        """
        from .services import ROOM_FIELDS, clean_room

        values = common.changes_dict(changes)
        common.refuse_unknown(values, ROOM_FIELDS)
        clean = clean_room(values, partial=True)
        row = common.row(actor, Room, room_id, field="room_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        common.apply_changes(row, clean)
        return room_info(row)

    @service_method(read_only=True, since="0.1.0")
    def appointment_types(self, *, actor: Any, active_only: bool = True) -> tuple[AppointmentTypeInfo, ...]:
        """Kinds of appointment of the practice.

        Autorização: leitura do consultório.
        Erros: NotFound sem consultório legível.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        practice = _practice(actor)
        rows = authorized_queryset(AppointmentType, user=actor, action="read").filter(practice=practice)
        if active_only:
            rows = rows.filter(is_active=True)
        return tuple(type_info(row) for row in rows.order_by("name", "sysid")[:200])

    @service_method(read_only=False, since="0.1.0")
    def add_appointment_type(
        self,
        *,
        actor: Any,
        code: str,
        name: str,
        duration_minutes: int = 30,
        color: str = "blue",
        billing_code: str = "",
        requires_room: bool = False,
        idempotency_key: str | None = None,
        payment_kind: str = "private",
    ) -> AppointmentTypeInfo:
        """Add a kind of appointment; the code is unique in the practice.

        The kind says how it is paid for ("private", "insurance" or "courtesy"): an appointment
        booked with it starts with that payment kind.
        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("integrity_conflict") para código já usado.
        Efeitos: grava o tipo; a mesma chave do mesmo ator devolve o já criado.
        """
        from .services import clean_type

        values = clean_type(
            {
                "code": code,
                "name": name,
                "duration_minutes": duration_minutes,
                "payment_kind": payment_kind,
                "color": color,
                "billing_code": billing_code,
                "requires_room": requires_room,
            },
            partial=False,
        )
        practice = _practice(actor, write=True)
        row = _new_child(actor, AppointmentType, practice, idempotency_key, "type")
        existing = AppointmentType.objects.filter(pk=row.sysid).first() if idempotency_key is not None else None
        if existing is not None:
            return type_info(existing)
        for field, value in values.items():
            setattr(row, field, value)
        row.save()
        return type_info(row)

    @service_method(read_only=False, since="0.1.0")
    def update_appointment_type(
        self, *, actor: Any, type_id: UUID, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> AppointmentTypeInfo:
        """Change a kind of appointment, with CAS; the code never changes.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram; consultas já marcadas guardam a cópia do código de
        cobrança e da forma de pagamento.
        """
        from .services import TYPE_FIELDS, clean_type

        values = common.changes_dict(changes)
        common.refuse_unknown(values, TYPE_FIELDS)
        clean = clean_type(values, partial=True)
        row = common.row(actor, AppointmentType, type_id, field="type_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        common.apply_changes(row, clean)
        return type_info(row)

    # ------------------------------------------------------------------ schedules

    @service_method(read_only=True, since="0.1.0")
    def schedules(self, *, actor: Any, active_only: bool = True) -> tuple[ScheduleInfo, ...]:
        """Schedules the actor reads, by name.

        Autorização: leitura de cada agenda.
        Erros: Forbidden sem a permissão de tabela das agendas.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Schedule, user=actor, action="read")
        if active_only:
            rows = rows.filter(is_active=True)
        writable = _writable_schedule_ids(actor)
        return tuple(schedule_info(row, writable=row.pk in writable) for row in rows.order_by("name", "sysid")[:200])

    @service_method(read_only=True, since="0.1.0")
    def schedule(self, *, actor: Any, schedule_id: UUID) -> ScheduleInfo:
        """One schedule.

        Autorização: leitura da agenda.
        Erros: NotFound para agenda inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        row = _schedule(actor, schedule_id)
        return schedule_info(row, writable=row.pk in _writable_schedule_ids(actor))

    @service_method(read_only=True, since="0.1.0")
    def calendars(self, *, actor: Any) -> tuple[CalendarEntry, ...]:
        """The calendars of the core the actor reads: those of the schedules by name, then the others.

        The calendar of a schedule shows its appointments and follows its rules; any other (a
        personal or a shared one) holds common events of the core calendar. Nothing is created:
        the personal calendar of a person exists after their first visit to the core calendar.
        Autorização: cada calendário pela leitura dele no núcleo, e a agenda dele pela leitura da agenda.
        Erros: Unavailable com a agenda do núcleo desativada.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        from . import calendar_bridge

        schedules = {row.calendar_id: row for row in authorized_queryset(Schedule, user=actor, action="read")[:200]}
        of_schedules, others = [], []
        for info in calendar_bridge.readable_calendars(actor)[:200]:
            schedule = schedules.get(info.sysid)
            if schedule is not None:
                of_schedules.append(
                    CalendarEntry(
                        info.sysid,
                        schedule.name,
                        info.kind,
                        schedule_id=schedule.pk,
                        schedule_is_active=schedule.is_active,
                    )
                )
            else:
                own = info.kind == "personal" and info.owner_id == actor.pk
                others.append(CalendarEntry(info.sysid, info.name, info.kind, is_own=own))
        of_schedules.sort(key=lambda entry: (entry.name.casefold(), str(entry.calendar_id)))
        return (*of_schedules, *others)

    @service_method(read_only=False, since="0.1.0")
    def create_schedule(
        self,
        *,
        actor: Any,
        name: str,
        professional_id: UUID | None = None,
        room_id: UUID | None = None,
        slot_minutes: int = 30,
        writer_group_ids: tuple[UUID, ...] = (),
        reader_group_ids: tuple[UUID, ...] = (),
        writer_user_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> ScheduleInfo:
        """Create the schedule of a professional or room, with its shared calendar and the same access.

        The owner is the professional's person (or the actor, for a room): the owner always writes.
        Autorização: a capacidade ``access.manage`` e ``create`` em med_scheduling.schedule.
        Erros: Forbidden; NotFound para profissional ou sala ilegível; InvalidInput para nome vazio,
        sem profissional nem sala, intervalo fora de 5 a 120 minutos, mais de 20 grupos ou pessoas;
        Unavailable com a agenda do núcleo desativada.
        Efeitos: cria o calendário compartilhado, a agenda e as concessões nas duas, na transação do
        chamador; a mesma chave do mesmo ator devolve a agenda já criada.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.organizations import OrganizationService

        from . import calendar_bridge

        key = common.key(idempotency_key)
        writers = common.group_ids(writer_group_ids, "writer_group_ids")
        readers = tuple(
            group for group in common.group_ids(reader_group_ids, "reader_group_ids") if group not in writers
        )
        users = common.group_ids(writer_user_ids, "writer_user_ids")
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 120:
            raise InvalidInput({"name": [gettext("Informe o nome da agenda (até 120 caracteres).")]})
        if type(slot_minutes) is not int or not 5 <= slot_minutes <= 120:
            raise InvalidInput({"slot_minutes": [gettext("Use de 5 a 120 minutos.")]})
        if professional_id is None and room_id is None:
            raise InvalidInput({"professional_id": [gettext("Escolha o profissional ou a sala da agenda.")]})
        common.require_access_manager(actor)
        if not has_table_permission(Schedule, user=actor, action="create"):
            raise Forbidden()
        sysid = common.deterministic_id("schedule", actor, key)
        existing = Schedule.objects.filter(pk=sysid).first()
        if existing is not None:
            return schedule_info(existing, writable=True)
        practice = _practice(actor)
        professional = (
            common.row(actor, Professional, professional_id, field="professional_id", write=False)
            if professional_id is not None
            else None
        )
        room = common.row(actor, Room, room_id, field="room_id", write=False) if room_id is not None else None
        if users and len(OrganizationService().member_refs(actor=actor, user_ids=users)) != len(users):
            raise InvalidInput({"writer_user_ids": [gettext("Toda pessoa precisa ser membro ativo da organização.")]})
        owner = professional.user_id if professional is not None and professional.user_id else actor.pk
        calendar_id = calendar_bridge.create_calendar(
            actor,
            name=clean_name,
            owner_user_id=owner,
            timezone=practice.timezone,
            writer_group_ids=writers,
            reader_group_ids=readers,
            idempotency_key=key,
        )
        schedule = Schedule(
            sysid=sysid,
            organization_id=practice.organization_id,
            owner_id=owner,
            visibility=Schedule.Visibility.PRIVATE,
            practice=practice,
            name=clean_name,
            professional=professional,
            room=room,
            calendar_id=calendar_id,
            slot_minutes=slot_minutes,
        )
        schedule.save()
        calendar_bridge.mirror_access(
            actor,
            schedule,
            writer_groups={str(group) for group in writers},
            reader_groups={str(group) for group in readers},
            writer_users={str(user) for user in users},
        )
        schedule.writer_groups = sorted(str(group) for group in writers)
        schedule.reader_groups = sorted(str(group) for group in readers)
        schedule.writer_users = sorted(str(user) for user in users)
        schedule.save(update_fields={"writer_groups", "reader_groups", "writer_users"})
        return schedule_info(schedule, writable=True)

    @service_method(read_only=False, since="0.1.0")
    def update_schedule(
        self, *, actor: Any, schedule_id: UUID, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> ScheduleInfo:
        """Rename a schedule, change its slot, booking horizon or activity, with CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram.
        """
        values = common.changes_dict(changes)
        common.refuse_unknown(values, ("name", "slot_minutes", "booking_horizon_days", "is_active"))
        if "name" in values and not str(values["name"] or "").strip():
            raise InvalidInput({"name": [gettext("Informe o nome da agenda.")]})
        if "slot_minutes" in values and (
            type(values["slot_minutes"]) is not int or not 5 <= values["slot_minutes"] <= 120
        ):
            raise InvalidInput({"slot_minutes": [gettext("Use de 5 a 120 minutos.")]})
        if "booking_horizon_days" in values and (
            type(values["booking_horizon_days"]) is not int or not 1 <= values["booking_horizon_days"] <= 730
        ):
            raise InvalidInput({"booking_horizon_days": [gettext("Use de 1 a 730 dias.")]})
        if "name" in values:
            values["name"] = str(values["name"]).strip()
        if "is_active" in values:
            values["is_active"] = bool(values["is_active"])
        row = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(row, expected_revision)
        common.apply_changes(row, values)
        return schedule_info(row, writable=True)

    @service_method(read_only=False, since="0.1.0")
    def set_schedule_access(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        writer_group_ids: tuple[UUID, ...],
        reader_group_ids: tuple[UUID, ...],
        writer_user_ids: tuple[UUID, ...] = (),
        expected_revision: int,
    ) -> ScheduleInfo:
        """Share a schedule and its calendar, together, with exactly these groups and people, with CAS.

        This is the only way to change who sees and writes a schedule: changing the access of the
        schedule or of the calendar alone, on the core access pages, breaks the projection.
        Autorização: a capacidade ``access.manage``.
        Erros: Forbidden; NotFound; InvalidInput; Conflict("stale_revision").
        Efeitos: revoga nas duas o que saiu e concede o que entrou; vale na requisição seguinte.
        """
        from skeleton.service_api.organizations import OrganizationService

        from . import calendar_bridge

        writers = common.group_ids(writer_group_ids, "writer_group_ids")
        readers = tuple(
            group for group in common.group_ids(reader_group_ids, "reader_group_ids") if group not in writers
        )
        users = common.group_ids(writer_user_ids, "writer_user_ids")
        common.require_access_manager(actor)
        row = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(row, expected_revision)
        if users and len(OrganizationService().member_refs(actor=actor, user_ids=users)) != len(users):
            raise InvalidInput({"writer_user_ids": [gettext("Toda pessoa precisa ser membro ativo da organização.")]})
        calendar_bridge.mirror_access(
            actor,
            row,
            writer_groups={str(group) for group in writers},
            reader_groups={str(group) for group in readers},
            writer_users={str(user) for user in users},
        )
        row.writer_groups = sorted(str(group) for group in writers)
        row.reader_groups = sorted(str(group) for group in readers)
        row.writer_users = sorted(str(user) for user in users)
        row.save(update_fields={"writer_groups", "reader_groups", "writer_users"})
        return schedule_info(row, writable=True)

    # ------------------------------------------------------------------ availability and blocks

    @service_method(read_only=True, since="0.1.0")
    def availability(self, *, actor: Any, schedule_id: UUID) -> tuple[AvailabilityRuleInfo, ...]:
        """The weekly grid of a schedule, by weekday and start.

        Autorização: leitura da agenda.
        Erros: NotFound para agenda ilegível.
        Efeitos: nenhum.
        """
        return _availability(actor, _schedule(actor, schedule_id))

    @service_method(read_only=True, since="0.1.0")
    def schedule_types(self, *, actor: Any, schedule_id: UUID) -> tuple[ScheduleTypeInfo, ...]:
        """The kinds of appointment a schedule takes, by name, each with the duration it has there.

        A schedule nobody configured takes every active kind of the practice (``configured`` False).
        Autorização: leitura da agenda.
        Erros: NotFound para agenda inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        return _schedule_types(actor, _schedule(actor, schedule_id))

    @service_method(read_only=False, since="0.1.0")
    def set_schedule_types(
        self, *, actor: Any, schedule_id: UUID, types: tuple[ScheduleTypeInput, ...], expected_revision: int
    ) -> tuple[ScheduleTypeInfo, ...]:
        """Replace the kinds of appointment a schedule takes, with the schedule's revision as CAS.

        An empty list puts the schedule back to taking every active kind of the practice.
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para tipo desconhecido, inativo ou repetido, duração
        fora de 5 a 480 minutos ou tipo sem nenhum modo; Conflict("stale_revision").
        Efeitos: grava as linhas novas, altera as que mudaram, exclui logicamente as que saíram e dá
        uma revisão nova à agenda. As consultas já marcadas não mudam.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(schedule, expected_revision)
        wanted = _check_schedule_types(types, schedule, actor)
        for old in authorized_queryset(ScheduleAppointmentType, user=actor, action="delete").filter(schedule=schedule):
            if old.appointment_type_id not in wanted:
                old.delete()
        kept = {
            row.appointment_type_id: row
            for row in authorized_queryset(ScheduleAppointmentType, user=actor, action="update").filter(
                schedule=schedule
            )
        }
        for type_id, item in wanted.items():
            values = {
                "duration_minutes": item.duration_minutes,
                "allow_booked": item.allow_booked,
                "allow_walk_in": item.allow_walk_in,
            }
            row = kept.get(type_id)
            if row is None:
                ScheduleAppointmentType(
                    organization_id=schedule.organization_id, schedule=schedule, appointment_type_id=type_id, **values
                ).save()
            else:
                common.apply_changes(row, values)
        _bump(schedule)
        return _schedule_types(actor, schedule)

    @service_method(read_only=False, since="0.1.0")
    def set_availability(
        self, *, actor: Any, schedule_id: UUID, rules: tuple[AvailabilityRuleInput, ...], expected_revision: int
    ) -> tuple[AvailabilityRuleInfo, ...]:
        """Make the weekly grid of a schedule be ``rules``, with the schedule's revision as CAS.

        The grid is compared with what exists: a window that stays (same weekday, minutes and
        validity) keeps its row, and only what changed in it is written (kinds, mode, capacity). A
        window lists the kinds its period takes (none: every kind the schedule takes) and says its
        mode: booked time, or walk-in with an optional capacity.
        The exceptions of single days are not part of the grid: they stay as they are. The grid
        converts no appointment: a change that would leave an appointment from today on in a
        period of the other mode is refused (``availability_conflicts`` lists them), and passes
        once it holds from after the last of them, or once those days are changed one by one.
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para faixa inválida ou sobreposta, mais de 100
        faixas, modo desconhecido, vagas fora de 1 a 500 ou num período de hora marcada, ou tipo
        novo num período que seja desconhecido, inativo, de outra organização ou que a agenda não
        atende naquele modo; Conflict("stale_revision"); Conflict("plan_conflicts") quando a
        grade nova troca o modo de um período com consulta marcada de hoje em diante.
        Efeitos: grava as faixas novas, exclui logicamente as que saíram (os tipos delas antes) e
        acerta os tipos, o modo e as vagas das que ficaram; a agenda ganha uma revisão nova. As
        consultas já marcadas não mudam.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(schedule, expected_revision)
        wanted = _check_rules(rules)
        _refuse_mode_conflicts(actor, schedule, wanted)
        rows = authorized_queryset(AvailabilityRule, user=actor, action="delete").filter(
            schedule=schedule, on_date__isnull=True
        )
        _put_rules(actor, schedule, wanted, rows)
        _bump(schedule)
        return _availability(actor, schedule)

    @service_method(read_only=True, since="0.1.0")
    def day_exceptions(
        self, *, actor: Any, schedule_id: UUID, start_date: date | None = None, end_date: date | None = None
    ) -> tuple[DayException, ...]:
        """The days on which a schedule follows periods of their own in place of the weekly grid, by day.

        From ``start_date`` (today at the practice, when not given) to ``end_date`` (no end, when
        not given); at most 400 days come back.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda ilegível; InvalidInput para data inválida ou intervalo invertido.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id)
        first = _check_day(schedule, start_date, past=True) if start_date is not None else None
        if first is None:
            from django.utils import timezone as dj_timezone

            from . import plan

            first = plan.local_day(dj_timezone.now(), schedule.practice.timezone)
        rows = authorized_queryset(AvailabilityRule, user=actor, action="read").filter(
            schedule=schedule, on_date__gte=first
        )
        if end_date is not None:
            if _check_day(schedule, end_date, past=True) < first:
                raise InvalidInput({"end_date": [gettext("O fim precisa ser depois do início.")]})
            rows = rows.filter(on_date__lte=end_date)
        rows = list(rows.order_by("on_date", "start_minute", "sysid")[: 400 * MAX_DAY_WINDOWS])
        kinds = _rule_kinds(actor, rows)
        days: dict[Any, list[AvailabilityRuleInfo]] = {}
        for row in rows:
            days.setdefault(row.on_date, []).append(rule_info(row, kinds.get(row.pk, ())))
        return tuple(DayException(schedule.pk, day, tuple(found)) for day, found in list(days.items())[:400])

    @service_method(read_only=True, since="0.1.0")
    def plan_conflicts(
        self, *, actor: Any, schedule_id: UUID, date: date, windows: tuple[DayWindowInput, ...] | None = None
    ) -> tuple[PlanConflict, ...]:
        """What changing the periods of one day would do to the appointments already booked on it.

        ``windows`` are the periods the day would follow; ``None`` asks about going back to the
        weekly grid. Each appointment the new periods do not hold as it is comes with the reason:
        a move the owner confirms (``set_day_exception`` with ``convert_existing``), or a refusal.
        An appointment being attended and a fit-in with a time are never touched.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda ilegível; InvalidInput para data ou períodos inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id)
        day = _check_day(schedule, date, past=True)
        current = _schedule_windows(actor, schedule)
        wanted = [window for window in current if window.on_date != day]
        if windows is not None:
            wanted += _day_windows(_check_day_windows(windows, day), day)
        start, end = _day_window(day, day, schedule.practice.timezone)
        rows = _plan_rows(authorized_queryset(Appointment, user=actor, action="read"), schedule, start, end)
        return _plan_conflicts(actor, schedule, _plan_changes(schedule, rows, current, wanted), rows)

    @service_method(read_only=True, since="0.1.0")
    def availability_conflicts(
        self, *, actor: Any, schedule_id: UUID, rules: tuple[AvailabilityRuleInput, ...]
    ) -> tuple[PlanConflict, ...]:
        """The appointments from today on that a new weekly grid would leave in a period of the other mode.

        They are what makes ``set_availability`` answer ``plan_conflicts``: the grid has no mass
        conversion. The last of them says from when the change may hold.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda ilegível; InvalidInput para faixa inválida ou sobreposta.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id)
        readable = authorized_queryset(Appointment, user=actor, action="read")
        changes = _grid_changes(actor, schedule, _check_rules(rules), readable)
        return _plan_conflicts(actor, schedule, changes, [row for row, _reason, _period in changes])

    @service_method(read_only=False, since="0.1.0")
    def set_day_exception(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        date: date,
        windows: tuple[DayWindowInput, ...],
        expected_revision: int,
        convert_existing: bool = False,
        expected_affected: tuple[UUID, ...] | None = None,
    ) -> DayException:
        """Make one day of a schedule follow ``windows`` in place of the weekly grid, with the schedule's revision as CAS.

        The day keeps at least one period (to close a day, block it). An appointment with a time
        whose period becomes walk-in, and a walk-in one whose period changes its bounds, are moved
        to the session of the new period only with ``convert_existing`` and the exact list the
        owner saw (``expected_affected``, from ``plan_conflicts``): each keeps its code, loses its
        time and goes back to "agendada" when it was confirmed. The room of the session and the
        kinds of its period are not checked in the move.
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para dia que já passou, nenhum período, períodos
        sobrepostos ou inválidos, ou tipo que a agenda não atende no modo do período;
        Conflict("stale_revision"); Conflict("plan_conflicts") quando há consulta que a mudança
        não comporta (fora dos períodos novos, de ordem de chegada num período que vira hora
        marcada, ou com chegada registrada) ou que ela moveria sem ``convert_existing``;
        Conflict("plan_changed") quando as consultas a mover não são as de ``expected_affected``.
        Efeitos: grava os períodos do dia (os que ficam mantêm a linha), move as consultas
        confirmadas na lista, troca o evento de cada uma no calendário pelo da sessão, publica
        ``appointment_rescheduled`` de cada uma e dá revisão nova à agenda.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(schedule, expected_revision)
        day = _check_day(schedule, date)
        wanted = _check_day_windows(windows, day)
        kept = [window for window in _schedule_windows(actor, schedule) if window.on_date != day]
        moves = _replan_day(actor, schedule, day, kept + _day_windows(wanted, day), convert_existing, expected_affected)
        rows = authorized_queryset(AvailabilityRule, user=actor, action="delete").filter(schedule=schedule, on_date=day)
        _put_rules(actor, schedule, wanted, rows, on_date=day)
        _move_to_sessions(actor, schedule, moves)
        _bump(schedule)
        return DayException(schedule.pk, day, tuple(_exception_windows(actor, schedule, day)))

    @service_method(read_only=False, since="0.1.0")
    def clear_day_exception(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        date: date,
        expected_revision: int,
        convert_existing: bool = False,
        expected_affected: tuple[UUID, ...] | None = None,
    ) -> None:
        """Make one day of a schedule follow the weekly grid again, with the schedule's revision as CAS.

        The appointments of the day are treated as in ``set_day_exception``: what the weekly grid
        does not hold refuses the change, and what it would move asks for ``convert_existing``
        with the list the owner saw. A day without an exception stays as it is.
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para dia que já passou; Conflict("stale_revision",
        "plan_conflicts", "plan_changed").
        Efeitos: exclui logicamente os períodos do dia (os tipos deles antes), move as consultas
        confirmadas na lista como em ``set_day_exception`` e dá revisão nova à agenda.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(schedule, expected_revision)
        day = _check_day(schedule, date)
        kept = [window for window in _schedule_windows(actor, schedule) if window.on_date != day]
        moves = _replan_day(actor, schedule, day, kept, convert_existing, expected_affected)
        rows = authorized_queryset(AvailabilityRule, user=actor, action="delete").filter(schedule=schedule, on_date=day)
        _put_rules(actor, schedule, [], rows, on_date=day)
        _move_to_sessions(actor, schedule, moves)
        _bump(schedule)

    @service_method(read_only=True, since="0.1.0")
    def blocks(self, *, actor: Any, schedule_id: UUID, start: datetime, end: datetime) -> tuple[BlockInfo, ...]:
        """Blocks of a schedule that overlap a window.

        Autorização: leitura da agenda.
        Erros: NotFound; InvalidInput para janela sem fuso, invertida ou acima de 400 dias.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        start, end = _aware(start, "start"), _aware(end, "end")
        if end <= start or (end - start).days > 400:
            raise InvalidInput({"end": [gettext("Use uma janela de até 400 dias.")]})
        schedule = _schedule(actor, schedule_id)
        rows = authorized_queryset(ScheduleBlock, user=actor, action="read").filter(
            schedule=schedule, starts_at__lt=end, ends_at__gt=start
        )
        return tuple(block_info(row) for row in rows.order_by("starts_at", "sysid")[:500])

    @service_method(read_only=False, since="0.1.0")
    def add_block(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        reason: str = "other",
        note: str = "",
        idempotency_key: str | None = None,
    ) -> BlockInfo:
        """Block a period of a schedule; it shows as busy in the schedule's calendar too.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para período sem fuso ou invertido, motivo desconhecido
        ou observação acima de 200 caracteres.
        Efeitos: grava o bloqueio e o projeta no calendário como evento gerenciado ("Bloqueio").
        """
        from skeleton.access.policies import require_parent_action

        from . import calendar_bridge

        starts_at, ends_at = _aware(starts_at, "starts_at"), _aware(ends_at, "ends_at")
        if ends_at <= starts_at:
            raise InvalidInput({"ends_at": [gettext("O fim precisa ser depois do início.")]})
        if reason not in ScheduleBlock.Reason.values:
            raise InvalidInput({"reason": [gettext("Motivo desconhecido.")]})
        if len(str(note)) > 200:
            raise InvalidInput({"note": [gettext("Texto longo demais.")]})
        schedule = _schedule(actor, schedule_id, write=True)
        require_parent_action(ScheduleBlock, schedule, user=actor, action="create")
        row = ScheduleBlock(
            organization_id=schedule.organization_id,
            schedule=schedule,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=reason,
            note=str(note).strip(),
        )
        if idempotency_key is not None:
            row.sysid = common.deterministic_id("block", actor, common.key(idempotency_key))
            existing = ScheduleBlock.objects.filter(pk=row.sysid).first()
            if existing is not None:
                return block_info(existing)
        row.save()
        calendar_bridge.put_event(
            actor,
            source_key=f"block:{row.pk}",
            calendar_id=schedule.calendar_id,
            title=gettext("Bloqueio"),
            starts_at=starts_at,
            ends_at=ends_at,
            tzid=schedule.practice.timezone,
            attendee_user_ids=(),
            path=calendar_bridge.source_path(schedule.pk),
        )
        return block_info(row)

    @service_method(read_only=False, since="0.1.0")
    def remove_block(self, *, actor: Any, block_id: UUID, expected_revision: int) -> None:
        """Remove a block of a schedule, with CAS, and its calendar event.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; Conflict("stale_revision").
        Efeitos: exclusão lógica do bloqueio e do evento projetado.
        """
        from . import calendar_bridge

        row = common.row(actor, ScheduleBlock, block_id, field="block_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        row.delete()
        calendar_bridge.remove_event(actor, source_key=f"block:{row.pk}")

    # ------------------------------------------------------------------ free slots

    @service_method(read_only=True, since="0.1.0")
    def available_slots(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        start_date: date,
        end_date: date,
        appointment_type_id: UUID | None = None,
        duration_minutes: int | None = None,
    ) -> tuple[Slot, ...]:
        """Free slots of a schedule between two dates (inclusive, at most 62 days).

        A slot is free when it is inside the weekly grid (of the type, when the window restricts
        it), not in the past, not beyond the booking horizon, and crosses no block, no live
        appointment of the schedule and no busy interval of the professional in the calendar.
        The slot lasts ``duration_minutes`` when given; otherwise what the schedule gives the kind,
        then the duration of the kind, then the interval of the schedule. A kind the schedule does
        not take has no free slot.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda ou tipo ilegível; InvalidInput para intervalo invertido ou acima
        de 62 dias, ou duração fora de 5 a 480 minutos.
        Efeitos: nenhum.
        """
        from django.utils import timezone as dj_timezone

        from skeleton.access.policies import authorized_queryset

        from .slots import typed_slots

        if not isinstance(start_date, date) or not isinstance(end_date, date) or end_date < start_date:
            raise InvalidInput({"end_date": [gettext("O fim precisa ser depois do início.")]})
        if (end_date - start_date).days >= MAX_SLOT_DAYS:
            raise InvalidInput({"end_date": [gettext("Consulte no máximo 62 dias por vez.")]})
        schedule = _schedule(actor, schedule_id)
        practice = schedule.practice
        if duration_minutes is not None and (type(duration_minutes) is not int or not 5 <= duration_minutes <= 480):
            raise InvalidInput({"duration_minutes": [gettext("Use de 5 a 480 minutos.")]})
        duration = schedule.slot_minutes
        if appointment_type_id is not None:
            kind = common.row(actor, AppointmentType, appointment_type_id, field="appointment_type_id", write=False)
            own_duration = _type_duration(actor, schedule, kind)
            if own_duration is None:
                return ()
            duration = own_duration
        if duration_minutes is not None:
            duration = duration_minutes
        rules = authorized_queryset(AvailabilityRule, user=actor, action="read").filter(schedule=schedule)
        start, end = _day_window(start_date, end_date, practice.timezone)
        found = typed_slots(
            windows=_windows(actor, rules),
            taken=_taken(actor, schedule, start, end),
            start_date=start_date,
            end_date=end_date,
            slot_minutes=schedule.slot_minutes,
            duration_minutes=duration,
            timezone=practice.timezone,
            now=dj_timezone.now(),
            horizon_days=schedule.booking_horizon_days,
            appointment_type_id=appointment_type_id,
        )
        return tuple(Slot(start, end, schedule.pk, tuple(sorted(kinds, key=str))) for start, end, kinds in found)

    # ------------------------------------------------------------------ appointments

    @service_method(read_only=False, since="0.1.0")
    def book(
        self,
        *,
        actor: Any,
        schedule_id: UUID,
        patient_id: UUID,
        appointment_type_id: UUID,
        starts_at: datetime,
        duration_minutes: int | None = None,
        fit_in: bool = False,
        notes: str = "",
        payment_kind: str | None = None,
        room_id: UUID | None = None,
        idempotency_key: str,
        mode: str = "booked",
    ) -> AppointmentInfo:
        """Book an appointment; a fit-in skips the grid and the overlap check, never a block.

        The schedule is locked while the interval is checked: two bookings of the same slot never
        both win. The calendar of the schedule gets the event "<tipo> · <código>", never the patient.
        The kind must be active and taken by the schedule in the mode, fit-in or not. Without
        ``duration_minutes`` the appointment lasts what the schedule gives the kind, then the duration
        of the kind; without ``payment_kind`` it is paid for as the kind says.

        ``mode`` is explicit. "booked" takes the time asked for, which must be in a period of booked
        time. "walk_in" has no time: ``starts_at`` is any instant of a walk-in period, and the
        appointment takes the bounds of that period (its session) and keeps the planned duration.
        A session takes its capacity or, without one, the durations that fit its open minutes; the
        kind must be one the period lists. A fit-in skips the room of the session and the kinds of
        the period, and with a time it is taken inside a walk-in period too. The calendar gets one
        event per session ("Ordem de chegada · N pacientes"), not one per appointment.
        Autorização: alteração na agenda e leitura do paciente.
        Erros: NotFound (agenda, paciente, tipo ou sala ilegível); Forbidden se só lê a agenda;
        InvalidInput (horário sem fuso, duração fora de 5 a 480, modo, forma de pagamento,
        observação longa, sala exigida pelo tipo); Conflict("type_not_allowed", "slot_unavailable",
        "mode_mismatch" para hora num período de ordem de chegada ou o contrário, "session_full",
        "room_unavailable", "patient_inactive", "processing_restricted").
        Efeitos: código da sequência sem lacunas, consulta gravada, evento no calendário e
        ``med_scheduling.appointment_booked`` publicados; a mesma chave devolve a já marcada.
        """
        return appointment_info(
            _book(
                actor,
                schedule_id=schedule_id,
                patient_id=patient_id,
                appointment_type_id=appointment_type_id,
                starts_at=starts_at,
                duration_minutes=duration_minutes,
                fit_in=fit_in,
                notes=notes,
                payment_kind=payment_kind,
                room_id=room_id,
                idempotency_key=idempotency_key,
                mode=mode,
            )
        )

    @service_method(read_only=False, since="0.1.0")
    def reschedule(
        self,
        *,
        actor: Any,
        appointment_id: UUID,
        starts_at: datetime,
        expected_revision: int,
        schedule_id: UUID | None = None,
        idempotency_key: str | None = None,
        fit_in: bool | None = None,
        mode: str | None = None,
    ) -> AppointmentInfo:
        """Move an appointment to another time (same duration), with CAS; to another schedule, a new one.

        In the same schedule the appointment keeps its code and goes back to "agendada"; to another
        schedule the current one is cancelled ("remarcada") and a new one is booked pointing to it.
        It stays the fit-in or the regular appointment it was, unless ``fit_in`` says otherwise, and
        in the mode it had, unless ``mode`` says otherwise: to "walk_in", ``starts_at`` is an instant
        of the walk-in period it goes to, as in ``book``. A walk-in appointment whose patient already
        arrived is not moved, nor is an arrived one moved into a session: the queue keeps its numbers.
        The schedules are locked before the appointment, in the order of their ids.
        Autorização: alteração na agenda atual (e na nova, quando outra).
        Erros: NotFound; Forbidden; InvalidInput; Conflict("stale_revision", "invalid_transition",
        "slot_unavailable", "mode_mismatch", "session_full", "room_unavailable"; "type_not_allowed"
        quando a agenda de destino não atende o tipo, ou não naquele modo ou período).
        Efeitos: atualiza (ou cancela e cria) a consulta e os eventos do calendário (o da consulta
        ou o da sessão de onde sai e o da sessão aonde chega) e publica ``appointment_rescheduled``
        (ou ``appointment_cancelled`` e ``appointment_booked``).
        """
        from datetime import timedelta

        from . import calendar_bridge
        from .transitions import ARRIVED, CANCELLED, CONFIRMED, LIVE, SCHEDULED

        starts_at = _aware(starts_at, "starts_at")
        if fit_in is not None and type(fit_in) is not bool:
            raise InvalidInput({"fit_in": [gettext("Informe se é encaixe com verdadeiro ou falso.")]})
        if mode is not None:
            _check_mode(mode)
        # Read without a lock only to learn the schedule (it never changes), so that every operation
        # locks in the same order: the schedules by id, then the appointment.
        seen = _appointment(actor, appointment_id, write=True)
        common.check_revision(seen, expected_revision)
        target_id = seen.schedule_id if schedule_id is None else as_uuid(schedule_id, field="schedule_id")
        locked = {pk: _schedule(actor, pk, write=True, lock=True) for pk in sorted({seen.schedule_id, target_id})}
        row = _appointment(actor, appointment_id, write=True, lock=True)
        common.check_revision(row, expected_revision)
        if row.status not in LIVE or row.status == "in_progress":
            raise Conflict("invalid_transition", gettext("Esta consulta não pode mais ser remarcada."))
        target_mode = str(row.mode) if mode is None else mode
        if row.status == ARRIVED and WALK_IN in (row.mode, target_mode):
            raise Conflict(
                "invalid_transition",
                gettext("O paciente já chegou: na ordem de chegada a consulta não é remarcada."),
            )
        minutes = _planned(row)
        as_fit_in = row.is_fit_in if fit_in is None else fit_in
        left = (str(row.mode), row.starts_at)
        if target_id != row.schedule_id:
            from django.utils import timezone as dj_timezone

            row.status = CANCELLED
            row.cancel_reason = Appointment.CancelReason.RESCHEDULED
            row.cancelled_at = dj_timezone.now()
            row.save(update_fields={"status", "cancel_reason", "cancelled_at"})
            if left[0] == WALK_IN:
                _project_session(actor, locked[row.schedule_id], left[1])
            else:
                calendar_bridge.remove_event(actor, source_key=str(row.pk))
            _publish(actor, "cancelled", row)
            moved = _book(
                actor,
                schedule_id=target_id,
                patient_id=row.patient_id,
                appointment_type_id=row.appointment_type_id,
                starts_at=starts_at,
                duration_minutes=minutes,
                fit_in=as_fit_in,
                notes=row.notes,
                payment_kind=row.payment_kind,
                room_id=None,
                idempotency_key=idempotency_key or f"reschedule:{row.pk}:{starts_at.isoformat()}",
                rescheduled_from=row,
                mode=target_mode,
            )
            return appointment_info(moved)
        schedule = locked[row.schedule_id]
        kind = row.appointment_type
        if target_mode != row.mode and _type_duration(actor, schedule, kind, mode=target_mode) is None:
            raise _type_not_taken(target_mode)
        if target_mode == WALK_IN:
            period = _session_for(actor, schedule, starts_at)
            _check_session(actor, schedule, kind, period, minutes, fit_in=as_fit_in, room=row.room, ignore=row.pk)
            starts_at, ends_at = period.starts_at, period.ends_at
        else:
            ends_at = starts_at + timedelta(minutes=minutes)
            _check_interval(actor, schedule, kind, starts_at, ends_at, fit_in=as_fit_in, room=row.room, ignore=row.pk)
        values = {
            "starts_at": starts_at,
            "ends_at": ends_at,
            "is_fit_in": as_fit_in,
            "mode": target_mode,
            "duration_minutes": minutes,
            # The number belongs to the session the appointment leaves.
            "arrival_number": None,
        }
        if row.status == CONFIRMED:
            values["status"] = SCHEDULED
        common.apply_changes(row, values)
        if left[0] == WALK_IN:
            _project_session(actor, schedule, left[1])
        elif target_mode == WALK_IN:
            calendar_bridge.remove_event(actor, source_key=str(row.pk))
        _project(actor, row, schedule)
        _publish(actor, "rescheduled", row)
        return appointment_info(row)

    @service_method(read_only=False, since="0.1.0")
    def cancel(
        self, *, actor: Any, appointment_id: UUID, reason: str, expected_revision: int, note: str = ""
    ) -> AppointmentInfo:
        """Cancel an appointment (scheduled, confirmed or arrived), with CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para motivo desconhecido ou observação acima de 200
        caracteres; Conflict("stale_revision", "invalid_transition").
        Efeitos: grava a situação e o motivo, remove o evento do calendário (o de uma consulta de
        ordem de chegada é o da sessão, que passa a contar uma a menos e some com a última) e
        publica ``med_scheduling.appointment_cancelled``. O número de chegada fica com a cancelada.
        """
        from django.utils import timezone

        from . import calendar_bridge, transitions

        if reason not in Appointment.CancelReason.values:
            raise InvalidInput({"reason": [gettext("Motivo desconhecido.")]})
        if len(str(note)) > 200:
            raise InvalidInput({"note": [gettext("Texto longo demais.")]})
        schedule, row = _locked(actor, appointment_id, expected_revision)
        try:
            state = transitions.target("cancel", row.status)
        except transitions.InvalidTransition:
            raise Conflict("invalid_transition", gettext("Esta consulta não pode ser cancelada.")) from None
        common.apply_changes(
            row,
            {
                "status": state,
                "cancel_reason": reason,
                "cancel_note": str(note).strip(),
                "cancelled_at": timezone.now(),
            },
        )
        if row.mode == WALK_IN:
            _project_session(actor, schedule, row.starts_at)
        else:
            calendar_bridge.remove_event(actor, source_key=str(row.pk))
        _publish(actor, "cancelled", row)
        return appointment_info(row)

    @service_method(read_only=True, since="0.1.0")
    def appointment(self, *, actor: Any, appointment_id: UUID) -> AppointmentDetail:
        """One appointment with its notes and the times of each state.

        Autorização: leitura da agenda.
        Erros: NotFound para consulta inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        row = _appointment(actor, appointment_id)
        return appointment_detail(row, writable=row.schedule_id in _writable_schedule_ids(actor))

    @service_method(read_only=True, since="0.1.0")
    def appointments(
        self,
        *,
        actor: Any,
        schedule_id: UUID | None = None,
        patient_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[AppointmentInfo]:
        """Appointments of the schedules the actor reads, by start time, filtered.

        Autorização: leitura de cada agenda.
        Erros: InvalidInput para filtro, cursor ou tamanho de página inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Appointment, user=actor, action="read")
        if schedule_id is not None:
            rows = rows.filter(schedule_id=as_uuid(schedule_id, field="schedule_id"))
        if patient_id is not None:
            rows = rows.filter(patient_id=as_uuid(patient_id, field="patient_id"))
        if start is not None:
            rows = rows.filter(ends_at__gt=_aware(start, "start"))
        if end is not None:
            rows = rows.filter(starts_at__lt=_aware(end, "end"))
        if status is not None:
            if status not in Appointment.Status.values:
                raise InvalidInput({"status": [gettext("Situação desconhecida.")]})
            rows = rows.filter(status=status)
        return paginate(rows, convert=appointment_info, cursor=cursor, page_size=page_size, key=("starts_at", "sysid"))

    @service_method(read_only=True, since="0.1.0")
    def day(self, *, actor: Any, date: date, schedule_ids: tuple[UUID, ...] | None = None) -> tuple[DayAgenda, ...]:
        """The appointments and free slots of one local day, for every schedule the actor reads.

        The free slots are those of every window of booked time of the day, whatever the kinds a
        window is restricted to; each slot says the kinds of its window. ``sessions`` are the
        walk-in sessions of the day with their queues. The number of queries does not grow with the
        number of appointments or of windows.
        Autorização: leitura de cada agenda.
        Erros: InvalidInput para data inválida ou mais de 20 agendas.
        Efeitos: nenhum.
        """
        from django.utils import timezone as dj_timezone

        from skeleton.access.policies import authorized_queryset

        from . import calendar_bridge, plan
        from .slots import typed_slots, windows_of
        from .transitions import LIVE

        day = date
        if not isinstance(day, type(dj_timezone.localdate())):
            raise InvalidInput({"date": [gettext("Informe uma data.")]})
        schedules = authorized_queryset(Schedule, user=actor, action="read").filter(is_active=True)
        if schedule_ids is not None:
            if not isinstance(schedule_ids, tuple) or len(schedule_ids) > 20:
                raise InvalidInput({"schedule_ids": [gettext("Informe até 20 agendas.")]})
            schedules = schedules.filter(pk__in=[as_uuid(value, field="schedule_ids") for value in schedule_ids])
        schedules = list(schedules.select_related("practice", "professional").order_by("name", "sysid")[:20])
        if not schedules:
            return ()
        timezone = schedules[0].practice.timezone
        start, end = _day_window(day, day, timezone)
        ids = [schedule.pk for schedule in schedules]
        appointments: dict[UUID, list[Appointment]] = {pk: [] for pk in ids}
        for row in (
            authorized_queryset(Appointment, user=actor, action="read")
            .filter(schedule_id__in=ids, starts_at__lt=end, ends_at__gt=start)
            .order_by("starts_at", "sysid")
        ):
            appointments[row.schedule_id].append(row)
        rules: dict[UUID, list[AvailabilityRule]] = {pk: [] for pk in ids}
        for rule in authorized_queryset(AvailabilityRule, user=actor, action="read").filter(schedule_id__in=ids):
            rules[rule.schedule_id].append(rule)
        # The kinds of every window of the day's schedules in one query, whatever the number of windows.
        rule_kinds = _rule_kinds(actor, [rule for found in rules.values() for rule in found])
        blocks: dict[UUID, list[tuple[datetime, datetime]]] = {pk: [] for pk in ids}
        for block in authorized_queryset(ScheduleBlock, user=actor, action="read").filter(
            schedule_id__in=ids, starts_at__lt=end, ends_at__gt=start
        ):
            blocks[block.schedule_id].append((block.starts_at, block.ends_at))
        people = tuple({s.professional.user_id for s in schedules if s.professional_id and s.professional.user_id})
        busy: dict[UUID, list[tuple[datetime, datetime]]] = {}
        for block in calendar_bridge.busy_of_people(actor, user_ids=people, start=start, end=end):
            busy.setdefault(block.user_id, []).append((block.starts_at, block.ends_at))
        writable = _writable_schedule_ids(actor)
        now = dj_timezone.now()
        result = []
        for schedule in schedules:
            live = [(row.starts_at, row.ends_at) for row in appointments[schedule.pk] if row.status in LIVE]
            person = schedule.professional.user_id if schedule.professional_id else None
            windows = windows_of(rules[schedule.pk], rule_kinds)
            free = typed_slots(
                windows=windows,
                taken=blocks[schedule.pk] + live + busy.get(person, []),
                start_date=day,
                end_date=day,
                slot_minutes=schedule.slot_minutes,
                duration_minutes=schedule.slot_minutes,
                timezone=schedule.practice.timezone,
                now=now,
                horizon_days=schedule.booking_horizon_days,
                any_type=True,
            )
            result.append(
                DayAgenda(
                    schedule_info(schedule, writable=schedule.pk in writable),
                    tuple(appointment_info(row) for row in appointments[schedule.pk]),
                    tuple(
                        Slot(slot_start, slot_end, schedule.pk, tuple(sorted(kinds, key=str)))
                        for slot_start, slot_end, kinds in free
                    ),
                    _sessions(
                        schedule.pk,
                        day,
                        plan.periods_on(windows, day, schedule.practice.timezone),
                        appointments[schedule.pk],
                        blocks[schedule.pk],
                    ),
                )
            )
        return tuple(result)

    @service_method(read_only=True, since="0.1.0")
    def day_plan(self, *, actor: Any, schedule_id: UUID, start_date: date, end_date: date) -> tuple[PeriodPlan, ...]:
        """The periods a schedule works between two local dates (inclusive, at most 62 days), with what is taken.

        Each period says its mode, its capacity, the kinds it takes (none: every kind of the
        schedule) and how many appointments and minutes it already holds.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda ilegível; InvalidInput para intervalo invertido ou acima de 62 dias.
        Efeitos: nenhum.
        """
        from datetime import timedelta

        from skeleton.access.policies import authorized_queryset

        from . import plan
        from .transitions import CANCELLED

        if not isinstance(start_date, date) or not isinstance(end_date, date) or end_date < start_date:
            raise InvalidInput({"end_date": [gettext("O fim precisa ser depois do início.")]})
        if (end_date - start_date).days >= MAX_SLOT_DAYS:
            raise InvalidInput({"end_date": [gettext("Consulte no máximo 62 dias por vez.")]})
        schedule = _schedule(actor, schedule_id)
        timezone = schedule.practice.timezone
        windows = _schedule_windows(actor, schedule)
        start, end = _day_window(start_date, end_date, timezone)
        blocked = _blocked(actor, schedule, start, end)
        rows = list(
            authorized_queryset(Appointment, user=actor, action="read")
            .filter(schedule=schedule, starts_at__lt=end, ends_at__gt=start, is_fit_in=False)
            .exclude(status=CANCELLED)
            .only("mode", "starts_at", "ends_at", "duration_minutes")
        )
        result = []
        day = start_date
        while day <= end_date:
            for period in plan.periods_on(windows, day, timezone):
                if period.mode == WALK_IN:
                    planned = [
                        _planned(row) for row in rows if row.mode == WALK_IN and row.starts_at == period.starts_at
                    ]
                else:
                    planned = [
                        _planned(row)
                        for row in rows
                        if row.mode != WALK_IN and period.starts_at <= row.starts_at < period.ends_at
                    ]
                result.append(
                    PeriodPlan(
                        schedule.pk,
                        day,
                        period.start_minute,
                        period.end_minute,
                        as_utc(period.starts_at),
                        as_utc(period.ends_at),
                        period.mode,
                        period.capacity,
                        tuple(sorted(period.kinds, key=str)),
                        len(planned),
                        sum(planned),
                        plan.open_minutes(period, blocked),
                        period.mode == WALK_IN and plan.is_full(period, planned, MIN_DURATION, blocked=blocked),
                        period.is_exception,
                    )
                )
            day += timedelta(days=1)
        return tuple(result)

    @service_method(read_only=True, since="0.1.0")
    def queue(self, *, actor: Any, schedule_id: UUID, date: date) -> tuple[QueueSession, ...]:
        """The walk-in sessions of a schedule on one local day, each with its queue.

        Who waits is in the call order: legal priority first, then the arrival number. The priority
        mark is sensitive and leaves only here and in the detail of an appointment. The patient is
        an id: the name comes from the patients service, for whoever reads the patient.
        Autorização: leitura da agenda.
        Erros: NotFound para agenda inexistente, de outra organização ou ilegível; InvalidInput para data inválida.
        Efeitos: nenhum.
        """
        from django.utils import timezone as dj_timezone

        from skeleton.access.policies import authorized_queryset

        from . import plan

        day = date
        if not isinstance(day, type(dj_timezone.localdate())):
            raise InvalidInput({"date": [gettext("Informe uma data.")]})
        schedule = _schedule(actor, schedule_id)
        timezone = schedule.practice.timezone
        start, end = _day_window(day, day, timezone)
        rows = authorized_queryset(Appointment, user=actor, action="read").filter(
            schedule=schedule, mode=WALK_IN, starts_at__gte=start, starts_at__lt=end
        )
        return _sessions(
            schedule.pk,
            day,
            plan.periods_on(_schedule_windows(actor, schedule), day, timezone),
            list(rows),
            _blocked(actor, schedule, start, end),
        )

    # ------------------------------------------------------------------ attendance

    @service_method(read_only=False, since="0.1.0")
    def confirm(self, *, actor: Any, appointment_id: UUID, expected_revision: int) -> AppointmentInfo:
        """Confirm a scheduled appointment, with CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
        Efeitos: grava a situação e a hora e publica ``med_scheduling.appointment_confirmed``.
        """
        return appointment_info(_transition(actor, appointment_id, expected_revision, "confirm"))

    @service_method(read_only=False, since="0.1.0")
    def check_in(
        self, *, actor: Any, appointment_id: UUID, expected_revision: int, priority: bool = False
    ) -> AppointmentInfo:
        """Register that the patient arrived, with CAS, and tell the professional.

        In a walk-in session the arrival takes the next number of the session, given with the
        schedule locked: a number is never repeated nor used again, even after a cancellation.
        ``priority`` marks the legal priority (Lei 10.048), which puts the patient ahead in the
        queue; False leaves the mark as it is (``set_priority`` takes it off). The mark is sensitive:
        it is in no event and in no notification.
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para prioridade que não seja verdadeiro ou falso;
        Conflict("stale_revision", "invalid_transition"), sem dar número.
        Efeitos: grava a situação, a hora, o número de chegada e a prioridade, publica
        ``med_scheduling.appointment_arrived`` e notifica o profissional da agenda (uma vez por
        consulta; a notificação leva o código, nunca o paciente nem a prioridade).
        """
        from . import queue

        _check_flag(priority, "priority")

        def arrival(schedule: Schedule, row: Appointment) -> dict[str, Any]:
            values: dict[str, Any] = {"is_priority": row.is_priority or priority}
            if row.mode == WALK_IN:
                given = Appointment.all_objects.filter(schedule=schedule, mode=WALK_IN, starts_at=row.starts_at)
                values["arrival_number"] = queue.next_number(given.values_list("arrival_number", flat=True))
            return values

        row = _transition(actor, appointment_id, expected_revision, "check_in", extra=arrival)
        _notify_arrival(actor, row)
        return appointment_info(row)

    @service_method(read_only=False, since="0.1.0")
    def set_priority(
        self, *, actor: Any, appointment_id: UUID, priority: bool, expected_revision: int
    ) -> AppointmentInfo:
        """Set or take off the legal priority mark of an appointment not yet started, with CAS.

        The mark is sensitive: the answer does not carry it (``appointment`` and ``queue`` do).
        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para prioridade que não seja verdadeiro ou falso;
        Conflict("stale_revision"; "invalid_transition" fora de agendada, confirmada ou aguardando).
        Efeitos: grava a marca; nenhum evento nem notificação.
        """
        from .transitions import ARRIVED, CONFIRMED, SCHEDULED

        _check_flag(priority, "priority")
        _schedule_row, row = _locked(actor, appointment_id, expected_revision)
        if row.status not in (SCHEDULED, CONFIRMED, ARRIVED):
            raise Conflict("invalid_transition", gettext("A prioridade só muda antes do atendimento começar."))
        common.apply_changes(row, {"is_priority": priority})
        return appointment_info(row)

    @service_method(read_only=False, since="0.1.0")
    def start(self, *, actor: Any, appointment_id: UUID, expected_revision: int) -> AppointmentInfo:
        """Start the care of an arrived patient, with CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
        Efeitos: grava a situação e a hora e publica ``med_scheduling.appointment_started``.
        """
        return appointment_info(_transition(actor, appointment_id, expected_revision, "start"))

    @service_method(read_only=False, since="0.1.0")
    def complete(self, *, actor: Any, appointment_id: UUID, expected_revision: int) -> AppointmentInfo:
        """Finish an appointment (arrived or in progress), with CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
        Efeitos: grava a situação e a hora e publica ``med_scheduling.appointment_completed``.
        """
        return appointment_info(_transition(actor, appointment_id, expected_revision, "complete"))

    @service_method(read_only=False, since="0.1.0")
    def mark_no_show(self, *, actor: Any, appointment_id: UUID, expected_revision: int) -> AppointmentInfo:
        """Mark that the patient did not come, with CAS: after the start time, or after the end of a walk-in period.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
        Efeitos: grava a situação, mantém o evento no calendário e publica ``med_scheduling.appointment_no_show``.
        """
        return appointment_info(_transition(actor, appointment_id, expected_revision, "mark_no_show"))

    @service_method(read_only=True, since="0.1.0")
    def appointment_actions(self, *, actor: Any, appointment_id: UUID) -> tuple[AppointmentActionInfo, ...]:
        """Actions other apps registered for the current state of an appointment, in order.

        Autorização: leitura da agenda (cada ação autoriza a própria página).
        Erros: NotFound para consulta ilegível.
        Efeitos: nenhum.
        """
        from .extension import active_actions

        row = _appointment(actor, appointment_id)
        return tuple(
            AppointmentActionInfo(action.code, str(action.label), action.url_name, action.order)
            for action in active_actions(actor, row.status)
        )

    # ------------------------------------------------------------------ waitlist

    @service_method(read_only=True, since="0.1.0")
    def waitlist(
        self, *, actor: Any, status: str = "waiting", cursor: str | None = None, page_size: int = 50
    ) -> Page[WaitlistInfo]:
        """The waitlist of the practice, high priority first, then the oldest.

        Autorização: leitura do consultório.
        Erros: NotFound sem consultório; InvalidInput para situação, cursor ou página inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        if status not in WaitlistEntry.Status.values:
            raise InvalidInput({"status": [gettext("Situação desconhecida.")]})
        practice = _practice(actor)
        rows = authorized_queryset(WaitlistEntry, user=actor, action="read").filter(practice=practice, status=status)
        return paginate(
            rows.order_by(_priority_first(), "created_at", "sysid"),
            convert=waitlist_info,
            cursor=cursor,
            page_size=page_size,
        )

    @service_method(read_only=False, since="0.1.0")
    def add_to_waitlist(
        self,
        *,
        actor: Any,
        patient_id: UUID,
        earliest_date: date,
        appointment_type_id: UUID | None = None,
        schedule_id: UUID | None = None,
        preferred_period: str = "any",
        latest_date: date | None = None,
        priority: str = "normal",
        note: str = "",
        idempotency_key: str,
    ) -> WaitlistInfo:
        """Put a patient on the waitlist of the practice.

        Autorização: alteração no consultório e leitura do paciente.
        Erros: NotFound (consultório, paciente, tipo ou agenda ilegível); Forbidden se só lê o
        consultório; InvalidInput para período, prioridade, datas ou observação inválidos;
        Conflict("patient_inactive", "processing_restricted").
        Efeitos: grava a entrada; a mesma chave do mesmo ator devolve a já criada.
        """
        from skeleton.access.policies import require_parent_action

        key = common.key(idempotency_key)
        if preferred_period not in WaitlistEntry.Period.values:
            raise InvalidInput({"preferred_period": [gettext("Período desconhecido.")]})
        if priority not in WaitlistEntry.Priority.values:
            raise InvalidInput({"priority": [gettext("Prioridade desconhecida.")]})
        if not isinstance(earliest_date, date) or (latest_date is not None and latest_date < earliest_date):
            raise InvalidInput({"latest_date": [gettext("A última data é antes da primeira.")]})
        if len(str(note)) > 200:
            raise InvalidInput({"note": [gettext("Texto longo demais.")]})
        sysid = common.deterministic_id("waitlist", actor, key)
        existing = WaitlistEntry.objects.filter(pk=sysid).first()
        if existing is not None:
            return waitlist_info(existing)
        practice = _practice(actor, write=True)
        require_parent_action(WaitlistEntry, practice, user=actor, action="create")
        patient = _readable_patient(actor, patient_id)
        if appointment_type_id is not None:
            common.row(actor, AppointmentType, appointment_type_id, field="appointment_type_id", write=False)
        if schedule_id is not None:
            _schedule(actor, schedule_id)
        row = WaitlistEntry(
            sysid=sysid,
            organization_id=practice.organization_id,
            practice=practice,
            patient_id=patient.sysid,
            appointment_type_id=appointment_type_id,
            schedule_id=schedule_id,
            preferred_period=preferred_period,
            earliest_date=earliest_date,
            latest_date=latest_date,
            priority=priority,
            note=str(note).strip(),
        )
        row.save()
        return waitlist_info(row)

    @service_method(read_only=False, since="0.1.0")
    def cancel_waitlist_entry(self, *, actor: Any, entry_id: UUID, expected_revision: int) -> WaitlistInfo:
        """Take a patient off the waitlist, with CAS.

        Autorização: alteração no consultório.
        Erros: NotFound; Forbidden; Conflict("stale_revision", "invalid_transition") fora de "aguardando".
        Efeitos: grava a situação "cancelado".
        """
        row = common.row(actor, WaitlistEntry, entry_id, field="entry_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        if row.status != WaitlistEntry.Status.WAITING:
            raise Conflict("invalid_transition")
        common.apply_changes(row, {"status": WaitlistEntry.Status.CANCELLED})
        return waitlist_info(row)

    @service_method(read_only=True, since="0.1.0")
    def waitlist_candidates(
        self, *, actor: Any, schedule_id: UUID, starts_at: datetime, ends_at: datetime
    ) -> tuple[WaitlistInfo, ...]:
        """Waiting patients that fit a free time of a schedule: type, schedule, period and dates.

        High priority first, then the oldest. The reception decides; nobody is booked automatically.
        Autorização: leitura da agenda e do consultório.
        Erros: NotFound; InvalidInput para horário sem fuso ou invertido.
        Efeitos: nenhum.
        """
        from django.db.models import Q

        from skeleton.access.policies import authorized_queryset

        starts_at, ends_at = _aware(starts_at, "starts_at"), _aware(ends_at, "ends_at")
        if ends_at <= starts_at:
            raise InvalidInput({"ends_at": [gettext("O fim precisa ser depois do início.")]})
        schedule = _schedule(actor, schedule_id)
        timezone = schedule.practice.timezone
        from zoneinfo import ZoneInfo

        day = starts_at.astimezone(ZoneInfo(timezone)).date()
        minutes = int((ends_at - starts_at).total_seconds() // 60)
        rows = authorized_queryset(WaitlistEntry, user=actor, action="read").filter(
            Q(schedule__isnull=True) | Q(schedule=schedule),
            Q(latest_date__isnull=True) | Q(latest_date__gte=day),
            practice=schedule.practice,
            status=WaitlistEntry.Status.WAITING,
            earliest_date__lte=day,
        )
        rows = rows.select_related("appointment_type").order_by(_priority_first(), "created_at", "sysid")[:200]
        return tuple(
            waitlist_info(row)
            for row in rows
            if _fits_period(row.preferred_period, starts_at, timezone)
            and (row.appointment_type is None or row.appointment_type.duration_minutes <= minutes)
        )

    @service_method(read_only=False, since="0.1.0")
    def book_from_waitlist(
        self,
        *,
        actor: Any,
        entry_id: UUID,
        schedule_id: UUID,
        starts_at: datetime,
        expected_revision: int,
        idempotency_key: str,
        duration_minutes: int | None = None,
        mode: str = "booked",
    ) -> AppointmentInfo:
        """Book the appointment of a waiting patient and mark the entry booked, in one transaction.

        The kind is the one of the entry; without ``duration_minutes`` the appointment lasts what the
        schedule gives that kind. ``mode`` is the one of ``book``: "walk_in" puts the patient in the
        session of the walk-in period that holds ``starts_at``.
        Autorização: alteração no consultório e na agenda.
        Erros: NotFound; Forbidden; InvalidInput sem tipo de atendimento na entrada ou com duração
        fora de 5 a 480 minutos;
        Conflict("stale_revision", "invalid_transition", "type_not_allowed", "slot_unavailable",
        "mode_mismatch", "session_full"): com o horário ocupado, a sessão lotada ou o tipo não
        atendido pela agenda, a entrada continua aguardando.
        Efeitos: os de ``book`` e a entrada em "agendado" com a consulta.
        """
        entry = common.row(actor, WaitlistEntry, entry_id, field="entry_id", write=True, lock=True)
        common.check_revision(entry, expected_revision)
        if entry.status != WaitlistEntry.Status.WAITING:
            raise Conflict("invalid_transition")
        if entry.appointment_type_id is None:
            raise InvalidInput({"appointment_type_id": [gettext("Escolha o tipo de atendimento da entrada.")]})
        appointment = _book(
            actor,
            schedule_id=schedule_id,
            patient_id=entry.patient_id,
            appointment_type_id=entry.appointment_type_id,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            fit_in=False,
            notes="",
            payment_kind=None,
            room_id=None,
            idempotency_key=idempotency_key,
            mode=mode,
        )
        common.apply_changes(entry, {"status": WaitlistEntry.Status.BOOKED, "booked_appointment_id": appointment.pk})
        return appointment_info(appointment)
