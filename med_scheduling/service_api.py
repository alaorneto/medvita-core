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

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, ServiceAPI, as_uuid, service_method

from . import common
from .models import AppointmentType, AvailabilityRule, Practice, Professional, Room, Schedule, ScheduleBlock

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.scheduling"
PRACTICE_TABLE = "med_scheduling.practice"
SCHEDULE_TABLE = "med_scheduling.schedule"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (PRACTICE_TABLE, SCHEDULE_TABLE, "skeleton_calendar.calendar")
Scalar = str | int | bool | date | None

__all__ = [
    "APP_ID",
    "AppointmentTypeInfo",
    "AvailabilityRuleInfo",
    "AvailabilityRuleInput",
    "BlockInfo",
    "PracticeInfo",
    "ProfessionalInfo",
    "RoomInfo",
    "ScheduleInfo",
    "SchedulingService",
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
    )


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
class AvailabilityRuleInput:
    """A weekly window: ``weekday`` 0 (Monday) to 6, minutes of the day in the practice's time zone."""

    weekday: int
    start_minute: int
    end_minute: int
    valid_from: date
    valid_until: date | None = None
    appointment_type_id: UUID | None = None


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


def rule_info(row: AvailabilityRule) -> AvailabilityRuleInfo:
    return AvailabilityRuleInfo(
        row.pk,
        row.schedule_id,
        row.weekday,
        row.start_minute,
        row.end_minute,
        row.valid_from,
        row.valid_until,
        row.appointment_type_id,
    )


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


def _check_rules(rules: object, practice: Practice, actor: Any) -> list[AvailabilityRuleInput]:
    from skeleton.access.policies import authorized_queryset

    if (
        not isinstance(rules, tuple)
        or len(rules) > 100
        or not all(isinstance(rule, AvailabilityRuleInput) for rule in rules)
    ):
        raise InvalidInput({"rules": [gettext("Informe até 100 faixas (AvailabilityRuleInput).")]})
    types = set(
        authorized_queryset(AppointmentType, user=actor, action="read")
        .filter(practice=practice)
        .values_list("pk", flat=True)
    )
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
        if rule.appointment_type_id is not None and rule.appointment_type_id not in types:
            raise InvalidInput({"appointment_type_id": [gettext("Tipo de atendimento desconhecido.")]})
    ordered = sorted(rules, key=lambda rule: (rule.weekday, rule.start_minute))
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.weekday != first.weekday or second.start_minute >= first.end_minute:
                continue
            first_end = first.valid_until or date.max
            second_end = second.valid_until or date.max
            if second.valid_from <= first_end and first.valid_from <= second_end:
                raise InvalidInput({"rules": [gettext("Duas faixas da agenda se sobrepõem no mesmo dia.")]})
    return ordered


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
        outro profissional vivo.
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
        """Hook for the plan limits (epic F); the default allows."""

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
        Erros: NotFound; Forbidden; Conflict("stale_revision").
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
    ) -> AppointmentTypeInfo:
        """Add a kind of appointment; the code is unique in the practice.

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
        Efeitos: grava só os campos que mudaram; consultas já marcadas guardam a cópia do código de cobrança.
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
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id)
        rows = authorized_queryset(AvailabilityRule, user=actor, action="read").filter(schedule=schedule)
        return tuple(rule_info(row) for row in rows.order_by("weekday", "start_minute", "sysid"))

    @service_method(read_only=False, since="0.1.0")
    def set_availability(
        self, *, actor: Any, schedule_id: UUID, rules: tuple[AvailabilityRuleInput, ...], expected_revision: int
    ) -> tuple[AvailabilityRuleInfo, ...]:
        """Replace the whole weekly grid of a schedule, with the schedule's revision as CAS.

        Autorização: alteração na agenda.
        Erros: NotFound; Forbidden; InvalidInput para faixa inválida, sobreposta ou com tipo de outro
        consultório; Conflict("stale_revision").
        Efeitos: exclusão lógica das faixas antigas, as novas gravadas e uma revisão nova da agenda.
        """
        from skeleton.access.policies import authorized_queryset

        schedule = _schedule(actor, schedule_id, write=True, lock=True)
        common.check_revision(schedule, expected_revision)
        ordered = _check_rules(rules, schedule.practice, actor)
        for old in authorized_queryset(AvailabilityRule, user=actor, action="delete").filter(schedule=schedule):
            old.delete()
        created = []
        for rule in ordered:
            row = AvailabilityRule(
                organization_id=schedule.organization_id,
                schedule=schedule,
                weekday=rule.weekday,
                start_minute=rule.start_minute,
                end_minute=rule.end_minute,
                valid_from=rule.valid_from,
                valid_until=rule.valid_until,
                appointment_type_id=rule.appointment_type_id,
            )
            row.save()
            created.append(rule_info(row))
        _bump(schedule)
        return tuple(created)

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
