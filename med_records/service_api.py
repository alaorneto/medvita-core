"""Service API of the records app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Clinical content leaves only through the
methods that say so, and every such read is recorded in the chart's read trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone
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
from .extension import DocumentKind, SectionField, SectionType, register_document_kind, register_section_type
from .models import Archive, Encounter, EncounterSection, PatientChart

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.records"
ARCHIVE_TABLE = "med_records.archive"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (ARCHIVE_TABLE,)

__all__ = [
    "APP_ID",
    "ArchiveInfo",
    "ChartInfo",
    "DocumentKind",
    "EncounterHeader",
    "EncounterInfo",
    "RecordsService",
    "SectionField",
    "SealCheck",
    "SectionInfo",
    "SectionType",
    "register_document_kind",
    "register_section_type",
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


@dataclass(frozen=True, slots=True)
class EncounterHeader:
    """An encounter without clinical content: what lists show."""

    sysid: UUID
    chart_id: UUID
    patient_id: UUID
    code: str
    kind: str
    occurred_at: datetime
    author_id: UUID
    author_name: str
    author_council: str
    appointment_id: UUID | None
    amends_id: UUID | None
    signed: bool
    signed_at: datetime | None
    seal_digest: str
    revision: int


def encounter_header(row: Encounter) -> EncounterHeader:
    return EncounterHeader(
        row.pk,
        row.chart_id,
        row.patient_id,
        row.code,
        row.kind,
        as_utc(row.occurred_at),
        row.author_id,
        row.author_name,
        row.author_council,
        row.appointment_id,
        row.amends_id,
        row.sealed_at is not None,
        as_utc(row.sealed_at) if row.sealed_at else None,
        row.seal_digest,
        row.revision,
    )


@dataclass(frozen=True, slots=True)
class SectionInfo:
    """A section with its content; ``data_json`` is the structured data as canonical JSON text."""

    sysid: UUID
    section_type: str
    type_version: int
    position: int
    data_json: str
    text: str


def section_info(row: EncounterSection) -> SectionInfo:
    from skeleton.common.sealing import canonical_bytes

    return SectionInfo(
        row.pk, row.section_type, row.type_version, row.position, canonical_bytes(row.data).decode(), row.text
    )


@dataclass(frozen=True, slots=True)
class EncounterInfo:
    """An encounter with its sections (clinical content: every read is recorded in the trail)."""

    header: EncounterHeader
    sections: tuple[SectionInfo, ...]
    addenda: tuple[EncounterHeader, ...]
    writable: bool
    appointment_completed: bool = False


@dataclass(frozen=True, slots=True)
class SealCheck:
    """Whether a record is signed and whether its stored content still matches the seal."""

    sysid: UUID
    signed: bool
    valid: bool
    seal_digest: str
    signed_at: datetime | None


def seal_extra(encounter: Encounter) -> dict[str, Any]:
    """What the seal digest covers besides the frozen columns: the references and the sections.

    The references (chart, patient, author, appointment, amended encounter) are immutable from
    creation; the sections are frozen by ``seal_parent``. Stable order, no floats.
    """
    rows = EncounterSection.objects.filter(encounter_id=encounter.pk).order_by("sysid")
    return {
        "references": {
            "chart": encounter.chart_id,
            "patient": encounter.patient_id,
            "author": encounter.author_id,
            "appointment": encounter.appointment_id,
            "amends": encounter.amends_id,
        },
        "sections": [
            {
                "sysid": row.pk,
                "section_type": row.section_type,
                "type_version": row.type_version,
                "position": row.position,
                "data": row.data,
                "text": row.text,
            }
            for row in rows
        ]
    }


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


def _encounter(actor: Any, encounter_id: object, *, write: bool = False, lock: bool = False) -> Encounter:
    return common.row(actor, Encounter, encounter_id, field="encounter_id", write=write, lock=lock)


def _own_draft(actor: Any, encounter_id: object, expected_revision: object) -> Encounter:
    """A draft the actor wrote, locked, at the expected revision."""
    encounter = _encounter(actor, encounter_id, write=True, lock=True)
    if encounter.sealed_at is not None:
        raise Conflict("signed", gettext("O atendimento já foi assinado e não muda."))
    if encounter.author_id != actor.pk:
        raise Forbidden(gettext("Só o autor altera o rascunho."))
    common.check_revision(encounter, expected_revision)
    return encounter


def _touch(encounter: Encounter) -> None:
    """Bump the encounter's revision (the CAS of its sections) and the chart's last entry."""
    encounter.save(update_fields={"updated_at"})
    chart = PatientChart.objects.get(pk=encounter.chart_id)
    chart.last_entry_at = timezone.now()
    chart.save(update_fields={"last_entry_at"})


def _sections(actor: Any, encounter: Encounter) -> tuple[SectionInfo, ...]:
    from skeleton.access.policies import authorized_queryset

    rows = authorized_queryset(EncounterSection, user=actor, action="read").filter(encounter=encounter)
    return tuple(section_info(row) for row in rows.order_by("position", "section_type", "sysid"))


def _encounter_info(actor: Any, encounter: Encounter) -> EncounterInfo:
    from skeleton.access.policies import authorized_queryset

    addenda = authorized_queryset(Encounter, user=actor, action="read").filter(
        amends=encounter, sealed_at__isnull=False
    )
    writable = (
        encounter.sealed_at is None
        and encounter.author_id == actor.pk
        and encounter.chart.archive_id in _writable_ids(actor, Archive)
    )
    return EncounterInfo(
        encounter_header(encounter),
        _sections(actor, encounter),
        tuple(encounter_header(row) for row in addenda.order_by("sealed_at", "sysid")),
        writable,
    )


def _occurred(value: object) -> datetime:
    if value is None:
        return timezone.now()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidInput({"occurred_at": [gettext("Informe data e hora com fuso.")]})
    if value > timezone.now() + timedelta(minutes=5):
        raise InvalidInput({"occurred_at": [gettext("O atendimento não pode ser no futuro.")]})
    return value


def _new_encounter(
    actor: Any, chart: PatientChart, *, kind: str, occurred_at: datetime, sysid: UUID, **values: Any
) -> Encounter:
    from skeleton.access.policies import require_parent_action
    from skeleton.service_api.sequences import SequenceService

    from .registration import ENCOUNTER_SEQUENCE

    require_parent_action(Encounter, chart, user=actor, action="create")
    number = SequenceService().next_number(actor=actor, key=ENCOUNTER_SEQUENCE)
    encounter = Encounter(
        sysid=sysid,
        organization_id=chart.organization_id,
        chart=chart,
        patient_id=chart.patient_id,
        code=number.formatted,
        kind=kind,
        occurred_at=occurred_at,
        author_id=actor.pk,
        **values,
    )
    encounter.save()
    _touch(encounter)
    return encounter


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

    # ------------------------------------------------------------------ encounters

    @service_method(read_only=False, since="0.1.0")
    def start_encounter(
        self,
        *,
        actor: Any,
        chart_id: UUID,
        kind: str = "consultation",
        occurred_at: datetime | None = None,
        appointment_id: UUID | None = None,
        idempotency_key: str,
    ) -> EncounterInfo:
        """Start a draft encounter written by the actor; with an arrived appointment, start the attendance.

        Autorização: alteração no arquivo do prontuário; com ``appointment_id``, leitura da consulta.
        Erros: NotFound para prontuário ou consulta ilegíveis; Forbidden sem alteração no arquivo;
        InvalidInput para tipo desconhecido (o adendo nasce por ``add_addendum``), data futura ou
        consulta de outro paciente.
        Efeitos: cria o rascunho com o código da sequência e atualiza o último registro do
        prontuário; com a consulta em "chegou", tenta iniciá-la na agenda (recusa da agenda não
        impede o rascunho). A mesma chave devolve o mesmo rascunho.
        """
        key = common.key(idempotency_key)
        if kind not in Encounter.Kind.values or kind == Encounter.Kind.ADDENDUM:
            raise InvalidInput({"kind": [gettext("Tipo de atendimento desconhecido.")]})
        when = _occurred(occurred_at)
        sysid = common.deterministic_id("encounter", actor, key)
        existing = Encounter.objects.filter(pk=sysid).first()
        if existing is not None:
            return _encounter_info(actor, existing)
        chart = _chart(actor, chart_id, write=True)
        appointment = None
        if appointment_id is not None:
            from applications.med_scheduling.service_api import SchedulingService

            scheduling = SchedulingService()
            appointment = scheduling.appointment(
                actor=actor, appointment_id=as_uuid(appointment_id, field="appointment_id")
            ).appointment
            if appointment.patient_id != chart.patient_id:
                raise InvalidInput({"appointment_id": [gettext("A consulta é de outro paciente.")]})
        encounter = _new_encounter(
            actor,
            chart,
            kind=kind,
            occurred_at=when,
            sysid=sysid,
            appointment_id=appointment.sysid if appointment else None,
        )
        if appointment is not None and appointment.status == "arrived":
            try:
                scheduling.start(actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision)
            except (Forbidden, Conflict):
                pass
        return _encounter_info(actor, encounter)

    @service_method(read_only=True, since="0.1.0")
    def encounter(self, *, actor: Any, encounter_id: UUID) -> EncounterInfo:
        """One encounter with its sections and signed addenda; the read is recorded in the trail.

        Rascunhos aparecem a todos os leitores do arquivo, marcados como não assinados.
        Autorização: leitura do arquivo do prontuário.
        Erros: NotFound para atendimento inexistente, de outra organização ou ilegível.
        Efeitos: registra a leitura na trilha do prontuário.
        """
        from .trail import record_access

        encounter = _encounter(actor, encounter_id)
        record_access(actor, encounter.chart, "view_encounter", encounter)
        return _encounter_info(actor, encounter)

    @service_method(read_only=True, since="0.1.0")
    def encounters(
        self, *, actor: Any, chart_id: UUID, cursor: str | None = None, page_size: int = 50
    ) -> Page[EncounterHeader]:
        """Headers of the chart's encounters, newest first, without clinical content.

        Autorização: leitura do arquivo do prontuário.
        Erros: NotFound para prontuário ilegível; InvalidInput para cursor ou tamanho inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        chart = _chart(actor, chart_id)
        rows = (
            authorized_queryset(Encounter, user=actor, action="read")
            .filter(chart=chart)
            .order_by("-occurred_at", "-sysid")
        )
        return paginate(
            rows, convert=encounter_header, cursor=cursor, page_size=page_size, key=("-occurred_at", "-sysid")
        )

    @service_method(read_only=False, since="0.1.0")
    def save_section(
        self,
        *,
        actor: Any,
        encounter_id: UUID,
        section_type: str,
        data: tuple[tuple[str, Any], ...] = (),
        text: str = "",
        position: int = 0,
        expected_revision: int,
    ) -> EncounterInfo:
        """Write one section of the actor's draft (the section at ``section_type`` and ``position``).

        ``data`` are ``(field, value)`` pairs, validated by the section type (the latest version).
        Autorização: alteração no arquivo; só o autor do rascunho.
        Erros: NotFound; Forbidden para quem não é o autor; InvalidInput para tipo desconhecido ou
        campo inválido (citado pelo nome); Conflict("signed") ou Conflict("stale_revision").
        Efeitos: grava a seção, sobe a revisão do atendimento e o último registro do prontuário.
        """
        from skeleton.access.policies import require_parent_action

        from .extension import SECTION_TYPES, active_section_types
        from .sections import validate_section

        if type(position) is not int or not 0 <= position <= 50:
            raise InvalidInput({"position": [gettext("Use uma posição de 0 a 50.")]})
        values = common.changes_dict(tuple(data)) if data else {}
        kind = SECTION_TYPES.get(section_type) if isinstance(section_type, str) else None
        if kind is None or kind not in active_section_types(actor):
            raise InvalidInput({"section_type": [gettext("Tipo de seção desconhecido.")]})
        clean, clean_text = validate_section(kind, values, text)
        encounter = _own_draft(actor, encounter_id, expected_revision)
        row = EncounterSection.objects.filter(encounter=encounter, section_type=kind.code, position=position).first()
        if row is None:
            require_parent_action(EncounterSection, encounter, user=actor, action="create")
            row = EncounterSection(
                organization_id=encounter.organization_id,
                encounter=encounter,
                section_type=kind.code,
                position=position,
            )
        row.type_version = kind.version
        row.data = clean
        row.text = clean_text
        row.save()
        _touch(encounter)
        return _encounter_info(actor, encounter)

    @service_method(read_only=False, since="0.1.0")
    def remove_section(
        self, *, actor: Any, encounter_id: UUID, section_id: UUID, expected_revision: int
    ) -> EncounterInfo:
        """Remove one section of the actor's draft.

        Autorização: alteração no arquivo; só o autor do rascunho.
        Erros: NotFound; Forbidden; Conflict("signed") ou Conflict("stale_revision").
        Efeitos: exclusão lógica da seção e nova revisão do atendimento.
        """
        encounter = _own_draft(actor, encounter_id, expected_revision)
        row = EncounterSection.objects.filter(encounter=encounter, pk=as_uuid(section_id, field="section_id")).first()
        if row is None:
            raise NotFound()
        row.delete()
        _touch(encounter)
        return _encounter_info(actor, encounter)

    @service_method(read_only=False, since="0.1.0")
    def discard_draft(self, *, actor: Any, encounter_id: UUID, expected_revision: int) -> None:
        """Discard the actor's draft encounter with its sections.

        Autorização: alteração no arquivo; só o autor do rascunho.
        Erros: NotFound; Forbidden; Conflict("signed") para atendimento assinado; Conflict("stale_revision").
        Efeitos: exclusão lógica das seções e do atendimento.
        """
        encounter = _own_draft(actor, encounter_id, expected_revision)
        for row in EncounterSection.objects.filter(encounter=encounter):
            row.delete()
        encounter.delete()

    # ------------------------------------------------------------------ signing

    @service_method(read_only=False, since="0.1.0")
    def sign_encounter(self, *, actor: Any, encounter_id: UUID, expected_revision: int) -> EncounterInfo:
        """Sign the actor's draft: photograph the author, seal it and publish ``encounter_signed``.

        Sem assinatura digital ICP-Brasil: o selo é o resumo SHA-256 do conteúdo, que nunca mais muda.
        Com a consulta vinculada em atendimento, tenta concluí-la na agenda; a recusa da agenda não
        desfaz a assinatura (``appointment_completed`` diz o que aconteceu).
        Autorização: alteração no arquivo; só o autor do rascunho.
        Erros: NotFound; Forbidden; Conflict("empty") sem seção com conteúdo;
        Conflict("professional_required") sem ficha de profissional com conselho na agenda;
        Conflict("signed") ou Conflict("stale_revision").
        Efeitos: grava nome e conselho do autor, sela o atendimento com as seções e publica o evento.
        """
        from applications.med_scheduling.service_api import SchedulingService
        from skeleton.records.sealing import seal_record
        from skeleton.service_api.events import EventService

        encounter = _own_draft(actor, encounter_id, expected_revision)
        rows = list(EncounterSection.objects.filter(encounter=encounter))
        if not any(row.data or row.text.strip() for row in rows):
            raise Conflict("empty", gettext("O atendimento não tem nenhuma seção preenchida."))
        scheduling = SchedulingService()
        professional = scheduling.my_professional(actor=actor)
        if professional is None or not professional.council_label:
            raise Conflict("professional_required", gettext("Só um profissional com conselho cadastrado assina."))
        encounter.author_name = professional.display_name
        encounter.author_council = professional.council_label
        encounter.save(update_fields={"author_name", "author_council"})
        current = Encounter.objects.get(pk=encounter.pk)
        sealed = seal_record(current, user=actor, expected_revision=current.revision, extra=seal_extra(current))
        EventService().publish(
            actor=actor,
            event_type="med_records.encounter_signed",
            record_id=sealed.pk,
            data=(
                ("code", sealed.code),
                ("chart", str(sealed.chart_id)),
                ("patient", str(sealed.patient_id)),
                ("kind", sealed.kind),
                ("occurred_at", as_utc(sealed.occurred_at).isoformat()),
                ("seal_digest", sealed.seal_digest),
            ),
        )
        completed = False
        if sealed.appointment_id is not None:
            try:
                appointment = scheduling.appointment(actor=actor, appointment_id=sealed.appointment_id).appointment
                if appointment.status == "in_progress":
                    scheduling.complete(
                        actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision
                    )
                    completed = True
            except (Forbidden, Conflict, NotFound):
                completed = False
        info = _encounter_info(actor, sealed)
        return EncounterInfo(info.header, info.sections, info.addenda, info.writable, completed)

    @service_method(read_only=False, since="0.1.0")
    def add_addendum(self, *, actor: Any, encounter_id: UUID, text: str, idempotency_key: str) -> EncounterInfo:
        """Start a draft addendum (free text) to a signed encounter; it is signed by ``sign_encounter``.

        Qualquer profissional que altera o arquivo pode acrescentar um adendo; o original nunca muda.
        Autorização: alteração no arquivo do atendimento.
        Erros: NotFound; Forbidden; Conflict("not_signed") para atendimento não assinado ou que já
        é um adendo; InvalidInput para texto vazio ou longo demais.
        Efeitos: cria o rascunho do adendo com uma seção de texto livre.
        """
        from .sections import FREE_TEXT_LIMIT

        key = common.key(idempotency_key)
        if not isinstance(text, str) or not text.strip() or len(text) > FREE_TEXT_LIMIT:
            raise InvalidInput({"text": [gettext("Escreva o texto do adendo.")]})
        sysid = common.deterministic_id("addendum", actor, key)
        existing = Encounter.objects.filter(pk=sysid).first()
        if existing is not None:
            return _encounter_info(actor, existing)
        original = _encounter(actor, encounter_id, write=True)
        if original.sealed_at is None or original.kind == Encounter.Kind.ADDENDUM:
            raise Conflict("not_signed", gettext("Só um atendimento assinado recebe adendo."))
        addendum = _new_encounter(
            actor,
            original.chart,
            kind=Encounter.Kind.ADDENDUM,
            occurred_at=timezone.now(),
            sysid=sysid,
            amends=original,
        )
        EncounterSection(
            organization_id=addendum.organization_id,
            encounter=addendum,
            section_type="med_records.free_text",
            text=text,
        ).save()
        _touch(addendum)
        return _encounter_info(actor, addendum)

    @service_method(read_only=True, since="0.1.0")
    def verify_encounter(self, *, actor: Any, encounter_id: UUID) -> SealCheck:
        """Recompute the seal of an encounter from the stored content and its sections.

        Autorização: leitura do arquivo do atendimento.
        Erros: NotFound para atendimento inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        from skeleton.records.sealing import verify_seal

        encounter = _encounter(actor, encounter_id)
        valid = encounter.sealed_at is not None and verify_seal(encounter, extra=seal_extra(encounter))
        return SealCheck(
            encounter.pk,
            encounter.sealed_at is not None,
            valid,
            encounter.seal_digest,
            as_utc(encounter.sealed_at) if encounter.sealed_at else None,
        )
