"""Service API of the scheduling app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Besides ``SchedulingService`` it re-exports
the registry other apps call in ``ready()`` to add actions to an appointment (``extension.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, ServiceAPI, as_uuid, service_method

from . import common
from .models import AppointmentType, Practice, Professional, Room

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.scheduling"
PRACTICE_TABLE = "med_scheduling.practice"
SCHEDULE_TABLE = "med_scheduling.schedule"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (PRACTICE_TABLE,)
Scalar = str | int | bool | date | None

__all__ = [
    "APP_ID",
    "AppointmentTypeInfo",
    "PracticeInfo",
    "ProfessionalInfo",
    "RoomInfo",
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
