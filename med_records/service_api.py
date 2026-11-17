"""Service API of the records app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Clinical content leaves only through the
methods that say so, and every such read is recorded in the chart's read trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext

from skeleton.service_api import (
    Conflict,
    Forbidden,
    InvalidInput,
    NotFound,
    ServiceAPI,
    as_utc,
    as_uuid,
    service_method,
)

from . import common
from .models import Archive, PatientChart

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.records"
ARCHIVE_TABLE = "med_records.archive"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (ARCHIVE_TABLE,)

__all__ = [
    "APP_ID",
    "ArchiveInfo",
    "ChartInfo",
    "RecordsService",
]


# --------------------------------------------------------------------------------------- DTOs


@dataclass(frozen=True, slots=True)
class ArchiveInfo:
    sysid: UUID
    name: str
    kind: str
    is_default: bool
    revision: int
    writable: bool = False


def archive_info(row: Archive, *, writable: bool = False) -> ArchiveInfo:
    return ArchiveInfo(row.pk, row.name, row.kind, row.is_default, row.revision, writable)


@dataclass(frozen=True, slots=True)
class ChartInfo:
    """A chart without clinical content: which patient, which archive, when it was last written."""

    sysid: UUID
    archive_id: UUID
    patient_id: UUID
    opened_at: datetime
    last_entry_at: datetime | None
    revision: int
    writable: bool = False


def chart_info(row: PatientChart, *, writable: bool = False) -> ChartInfo:
    return ChartInfo(
        row.pk,
        row.archive_id,
        row.patient_id,
        as_utc(row.opened_at),
        as_utc(row.last_entry_at) if row.last_entry_at else None,
        row.revision,
        writable,
    )


# ------------------------------------------------------------------------------------ helpers


def _writable_ids(actor: Any, model: type) -> set[UUID]:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return set(authorized_queryset(model, user=actor, action="update").values_list("pk", flat=True))
    except PermissionDenied:
        return set()


def _archive(actor: Any, archive_id: object, *, write: bool = False) -> Archive:
    from skeleton.access.policies import authorized_queryset

    pk = as_uuid(archive_id, field="archive_id")
    if write:
        found = authorized_queryset(Archive, user=actor, action="update").filter(pk=pk).first()
        if found is not None:
            return found
    found = authorized_queryset(Archive, user=actor, action="read").filter(pk=pk).first()
    if found is None:
        raise NotFound()
    if write:
        raise Forbidden()
    return found


def _default_writable_archive(actor: Any) -> Archive:
    from skeleton.access.policies import authorized_queryset

    rows = list(authorized_queryset(Archive, user=actor, action="update").order_by("-is_default", "name")[:2])
    if not rows:
        raise Forbidden()
    if rows[0].is_default or len(rows) == 1:
        return rows[0]
    raise InvalidInput({"archive_id": [gettext("Escolha o arquivo clínico.")]})


def _chart(actor: Any, chart_id: object, *, write: bool = False) -> PatientChart:
    return common.row(actor, PatientChart, chart_id, field="chart_id", write=write)


def _readable_patient(actor: Any, patient_id: object) -> Any:
    from applications.med_patients.service_api import PatientService

    return PatientService().summary(actor=actor, patient_id=as_uuid(patient_id, field="patient_id"))


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise InvalidInput({"name": [gettext("Informe um nome de até 120 caracteres.")]})
    return value.strip()


def _user_ids(value: object, field: str) -> tuple[UUID, ...]:
    if not isinstance(value, tuple) or len(value) > 50:
        raise InvalidInput({field: [gettext("Informe até 50 pessoas.")]})
    return tuple(dict.fromkeys(as_uuid(item, field=field) for item in value))


def _grant(actor: Any, archive: Archive, *, groups: tuple[UUID, ...] = (), users: tuple[UUID, ...] = ()) -> None:
    from skeleton.service_api.access import AccessService

    access = AccessService()
    for action in ("read", "update"):
        for group in groups:
            access.grant_record_access(
                actor=actor, table_key=ARCHIVE_TABLE, record_id=archive.pk, action=action, group_id=group
            )
        for user in users:
            access.grant_record_access(
                actor=actor, table_key=ARCHIVE_TABLE, record_id=archive.pk, action=action, membership_user_id=user
            )


def _new_archive(actor: Any, *, sysid: UUID, name: str, kind: str, owner_id: Any, is_default: bool) -> Archive:
    from skeleton.tenancy.context import current_context

    archive = Archive(
        sysid=sysid,
        organization_id=current_context().organization_id,
        owner_id=owner_id,
        visibility=Archive.Visibility.PRIVATE,
        name=name,
        kind=kind,
        is_default=is_default,
    )
    archive.save()
    return archive


# ------------------------------------------------------------------------------------ service


class RecordsService(ServiceAPI):
    """The clinical record: archives, charts, encounters, clinical lists and simple documents."""

    app_label = APP_LABEL

    # ------------------------------------------------------------------ archives

    @service_method(read_only=False, since="0.1.0")
    def setup(
        self,
        *,
        actor: Any,
        mode: str = "shared",
        name: str = "",
        member_group_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> tuple[ArchiveInfo, ...]:
        """Create the first clinical archives of the organization.

        ``mode="shared"``: one default archive of the clinic, read and written by the groups in
        ``member_group_ids``. ``mode="per_professional"``: one personal archive for each active
        professional linked to a person, owned by that person and written by nobody else.
        Autorização: a capacidade ``access.manage`` e ``create`` em med_records.archive.
        Erros: Forbidden; InvalidInput para modo desconhecido, nome inválido, mais de 20 grupos ou
        nenhum profissional vinculado; Conflict("already_set_up") com arquivos criados por outra chave.
        Efeitos: cria os arquivos (privados), dá ao papel ``member`` leitura e alteração da tabela de
        arquivos e concede leitura e alteração aos grupos. A mesma chave devolve o já criado.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.access import AccessService

        key = common.key(idempotency_key)
        if mode not in ("shared", "per_professional"):
            raise InvalidInput({"mode": [gettext("Use 'shared' ou 'per_professional'.")]})
        groups = common.group_ids(member_group_ids, "member_group_ids")
        common.require_access_manager(actor)
        if not has_table_permission(Archive, user=actor, action="create"):
            raise Forbidden()
        if mode == "shared":
            plan = [(common.deterministic_id("archive", actor, key), _name(name or gettext("Prontuário da clínica")))]
            owners = [actor.pk]
        else:
            from applications.med_scheduling.service_api import SchedulingService

            people = [item for item in SchedulingService().professionals(actor=actor) if item.user_id is not None]
            if not people:
                raise InvalidInput({"mode": [gettext("Nenhum profissional ativo vinculado a uma pessoa.")]})
            plan = [
                (common.deterministic_id(f"archive:{item.sysid}", actor, key), _name(item.display_name[:120]))
                for item in people
            ]
            owners = [item.user_id for item in people]
        existing = list(Archive.objects.filter(pk__in=[sysid for sysid, _name_ in plan]))
        if existing:
            return tuple(archive_info(row, writable=True) for row in existing)
        if Archive.objects.exists():
            raise Conflict("already_set_up")
        access = AccessService()
        for table in MEMBER_TABLES:
            access.grant_member_table_access(actor=actor, table_key=table, actions=("read", "update"))
        created = []
        for (sysid, archive_name), owner in zip(plan, owners, strict=True):
            archive = _new_archive(
                actor,
                sysid=sysid,
                name=archive_name,
                kind=Archive.Kind.SHARED if mode == "shared" else Archive.Kind.PERSONAL,
                owner_id=owner,
                is_default=mode == "shared",
            )
            if mode == "shared":
                _grant(actor, archive, groups=groups)
            created.append(archive)
        return tuple(archive_info(row, writable=True) for row in created)

    @service_method(read_only=False, since="0.1.0")
    def create_archive(
        self,
        *,
        actor: Any,
        name: str,
        kind: str = "shared",
        owner_user_id: UUID | None = None,
        writer_group_ids: tuple[UUID, ...] = (),
        writer_user_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> ArchiveInfo:
        """Create one more clinical archive, written by the groups and people informed.

        Autorização: a capacidade ``access.manage`` e ``create`` em med_records.archive.
        Erros: Forbidden; InvalidInput para nome ou tipo inválidos, dono que não é membro ativo ou
        listas longas demais.
        Efeitos: cria o arquivo privado (dono ``owner_user_id`` ou o ator) e concede leitura e
        alteração aos grupos e pessoas. A mesma chave devolve o já criado.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.organizations import OrganizationService

        key = common.key(idempotency_key)
        clean_name = _name(name)
        if kind not in Archive.Kind.values:
            raise InvalidInput({"kind": [gettext("Tipo de arquivo desconhecido.")]})
        groups = common.group_ids(writer_group_ids, "writer_group_ids")
        users = _user_ids(writer_user_ids, "writer_user_ids")
        common.require_access_manager(actor)
        if not has_table_permission(Archive, user=actor, action="create"):
            raise Forbidden()
        owner = as_uuid(owner_user_id, field="owner_user_id") if owner_user_id is not None else actor.pk
        if owner != actor.pk and not OrganizationService().is_member(actor=actor, user_id=owner):
            raise InvalidInput({"owner_user_id": [gettext("O dono precisa ser membro ativo da organização.")]})
        sysid = common.deterministic_id("archive", actor, key)
        existing = Archive.objects.filter(pk=sysid).first()
        if existing is not None:
            return archive_info(existing, writable=True)
        archive = _new_archive(actor, sysid=sysid, name=clean_name, kind=kind, owner_id=owner, is_default=False)
        _grant(actor, archive, groups=groups, users=users)
        return archive_info(archive, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def archives(self, *, actor: Any) -> tuple[ArchiveInfo, ...]:
        """The clinical archives the actor reads, the default first.

        Autorização: leitura de cada arquivo.
        Erros: nenhum além do contrato.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Archive, user=actor, action="read").order_by("-is_default", "name", "sysid")
        writable = _writable_ids(actor, Archive)
        return tuple(archive_info(row, writable=row.pk in writable) for row in rows[:200])

    # ------------------------------------------------------------------ charts

    @service_method(read_only=False, since="0.1.0")
    def open_chart(
        self, *, actor: Any, patient_id: UUID, archive_id: UUID | None = None, idempotency_key: str | None = None
    ) -> ChartInfo:
        """The chart of the patient in the archive, created on first use (get or create).

        Without ``archive_id``, the default archive the actor writes (or the only one).
        Autorização: alteração no arquivo e leitura do paciente.
        Erros: NotFound para paciente ou arquivo ilegíveis; Forbidden sem alteração no arquivo;
        InvalidInput quando o ator altera vários arquivos e nenhum é o padrão.
        Efeitos: cria o prontuário uma vez; repetir devolve o mesmo.
        """
        from django.db import IntegrityError, transaction

        from skeleton.access.policies import require_parent_action

        if idempotency_key is not None:
            common.key(idempotency_key)
        patient = _readable_patient(actor, patient_id)
        archive = (
            _archive(actor, archive_id, write=True) if archive_id is not None else _default_writable_archive(actor)
        )
        require_parent_action(PatientChart, archive, user=actor, action="create")
        existing = PatientChart.objects.filter(archive=archive, patient_id=patient.sysid).first()
        if existing is not None:
            return chart_info(existing, writable=True)
        chart = PatientChart(
            organization_id=archive.organization_id,
            archive=archive,
            patient_id=patient.sysid,
            opened_at=timezone.now(),
        )
        try:
            with transaction.atomic():
                chart.save()
        except IntegrityError:
            chart = PatientChart.objects.get(archive=archive, patient_id=patient.sysid)
        return chart_info(chart, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def chart(self, *, actor: Any, chart_id: UUID) -> ChartInfo:
        """One chart, without clinical content.

        Autorização: leitura do arquivo.
        Erros: NotFound para prontuário inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        row = _chart(actor, chart_id)
        return chart_info(row, writable=row.archive_id in _writable_ids(actor, Archive))

    @service_method(read_only=True, since="0.1.0")
    def charts_for_patient(self, *, actor: Any, patient_id: UUID) -> tuple[ChartInfo, ...]:
        """The charts of a patient in the archives the actor reads.

        Autorização: leitura de cada arquivo; o paciente não é conferido (sem arquivo legível, vazio).
        Erros: InvalidInput para identificador inválido.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        pk = as_uuid(patient_id, field="patient_id")
        rows = authorized_queryset(PatientChart, user=actor, action="read").filter(patient_id=pk)
        writable = _writable_ids(actor, Archive)
        return tuple(chart_info(row, writable=row.archive_id in writable) for row in rows.order_by("opened_at")[:50])
