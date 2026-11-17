"""Service API of the patients app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Besides ``PatientService`` it re-exports the
registries other apps call in ``ready()`` to plug into the patient page (``extension.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
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
from skeleton.service_api.dto import DEFAULT_PAGE_SIZE

from .models import Patient, PatientRegistry
from .policies import (
    REGISTRY_TABLE,
    ids_allowed,
    readable_patients,
    readable_registries,
    writable_patients,
    writable_registries,
)

APP_LABEL = "med_patients"
APP_ID = "io.katua.sk.med.patients"
MAX_GROUPS = 20
MAX_SUMMARIES = 200
Scalar = str | int | bool | date | None

__all__ = [
    "APP_ID",
    "PatientInfo",
    "PatientInput",
    "PatientService",
    "PatientSummary",
    "RegistryInfo",
]


# --------------------------------------------------------------------------------------- DTOs


@dataclass(frozen=True, slots=True)
class RegistryInfo:
    sysid: UUID
    name: str
    is_default: bool
    revision: int
    writable: bool = False


def registry_info(registry: PatientRegistry, *, writable: bool = False) -> RegistryInfo:
    return RegistryInfo(registry.pk, registry.name, registry.is_default, registry.revision, writable)


@dataclass(frozen=True, slots=True)
class PatientSummary:
    """What other apps show of a patient in a list: never contacts, documents or address."""

    sysid: UUID
    code: str
    display_name: str
    birth_date: date | None
    status: str
    revision: int


def patient_summary(patient: Patient) -> PatientSummary:
    return PatientSummary(
        patient.pk, patient.code, patient.display_name, patient.birth_date, patient.status, patient.revision
    )


@dataclass(frozen=True, slots=True)
class PatientInfo:
    sysid: UUID
    registry_id: UUID
    code: str
    full_name: str
    social_name: str
    display_name: str
    birth_date: date | None
    sex: str
    cpf: str
    national_health_card: str
    identity_document: str
    mother_name: str
    phone: str
    phone_secondary: str
    email: str
    contact_preference: str
    postal_code: str
    street: str
    number: str
    complement: str
    district: str
    city: str
    state: str
    status: str
    deceased_on: date | None
    notes: str
    processing_restricted: bool
    anonymized_at: datetime | None
    revision: int
    updated_at: datetime
    writable: bool = False


def patient_info(patient: Patient, *, writable: bool = False) -> PatientInfo:
    return PatientInfo(
        sysid=patient.pk,
        registry_id=patient.registry_id,
        code=patient.code,
        full_name=patient.full_name,
        social_name=patient.social_name,
        display_name=patient.display_name,
        birth_date=patient.birth_date,
        sex=patient.sex,
        cpf=patient.cpf,
        national_health_card=patient.national_health_card,
        identity_document=patient.identity_document,
        mother_name=patient.mother_name,
        phone=patient.phone,
        phone_secondary=patient.phone_secondary,
        email=patient.email,
        contact_preference=patient.contact_preference,
        postal_code=patient.postal_code,
        street=patient.street,
        number=patient.number,
        complement=patient.complement,
        district=patient.district,
        city=patient.city,
        state=patient.state,
        status=patient.status,
        deceased_on=patient.deceased_on,
        notes=patient.notes,
        processing_restricted=patient.processing_restricted,
        anonymized_at=as_utc(patient.anonymized_at) if patient.anonymized_at else None,
        revision=patient.revision,
        updated_at=as_utc(patient.updated_at),
        writable=writable,
    )


@dataclass(frozen=True, slots=True)
class PatientInput:
    """The fields a person fills in to register a patient; ``full_name`` is the only required one."""

    full_name: str
    social_name: str = ""
    birth_date: date | None = None
    sex: str = "unknown"
    cpf: str = ""
    national_health_card: str = ""
    identity_document: str = ""
    mother_name: str = ""
    phone: str = ""
    phone_secondary: str = ""
    email: str = ""
    contact_preference: str = "phone"
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    notes: str = ""


# ------------------------------------------------------------------------------------ helpers


def _key(value: object, field: str = "idempotency_key") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidInput({field: [gettext("Use uma chave de 1 a 200 caracteres.")]})
    return value


def _revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise InvalidInput({"expected_revision": [gettext("Informe a revisão inteira do registro.")]})
    return value


def _group_ids(value: object, field: str) -> tuple[UUID, ...]:
    if not isinstance(value, tuple) or len(value) > MAX_GROUPS:
        raise InvalidInput({field: [gettext("Informe até 20 grupos.")]})
    return tuple(dict.fromkeys(as_uuid(item, field=field) for item in value))


def _require_access_manager(actor: Any) -> None:
    from skeleton.service_api.access import AccessService

    if "access.manage" not in AccessService().capabilities(actor=actor):
        raise Forbidden()


def _readable(actor: Any, patient_id: object, *, include_deleted: bool = False) -> Patient:
    pk = as_uuid(patient_id, field="patient_id")
    if include_deleted:
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Patient, user=actor, action="restore", include_deleted=True)
    else:
        rows = readable_patients(actor)
    patient = rows.select_related("registry").filter(pk=pk).first()
    if patient is None:
        raise NotFound()
    return patient


def _writable(actor: Any, patient_id: object, *, lock: bool = False) -> Patient:
    """The patient for a write: ``NotFound`` when unreadable, ``Forbidden`` when only readable."""
    pk = as_uuid(patient_id, field="patient_id")
    rows = writable_patients(actor)
    if lock:
        rows = rows.select_for_update()
    patient = rows.filter(pk=pk).first()
    if patient is None:
        _readable(actor, pk)  # NotFound when the actor does not even read it.
        raise Forbidden()
    return patient


def _check_revision(record: Any, expected_revision: int) -> None:
    if record.revision != _revision(expected_revision):
        raise Conflict("stale_revision")


def _require_changeable(patient: Patient) -> None:
    if patient.anonymized_at is not None:
        raise Conflict("anonymized", gettext("Paciente anonimizado: o cadastro é somente leitura."))
    if patient.processing_restricted:
        raise Conflict("processing_restricted", gettext("O tratamento dos dados deste paciente está restrito."))


def _publish(actor: Any, name: str, patient: Patient) -> None:
    from skeleton.service_api.events import EventService

    EventService().publish(
        actor=actor,
        event_type=f"{APP_LABEL}.{name}",
        record_id=patient.pk,
        data=(("code", patient.code), ("status", patient.status), ("registry", str(patient.registry_id))),
    )


def _default_writable_registry(actor: Any, registry_id: object) -> PatientRegistry:
    from skeleton.access.policies import require_parent_action

    if registry_id is not None:
        pk = as_uuid(registry_id, field="registry_id")
        registry = readable_registries(actor).filter(pk=pk).first()
    else:
        registry = readable_registries(actor).filter(is_default=True).first()
    if registry is None:
        raise NotFound()
    require_parent_action(Patient, registry, user=actor, action="create")
    return registry


# ------------------------------------------------------------------------------------ service


class PatientService(ServiceAPI):
    """Patients of the current organization: registry, identification, contacts and consents."""

    app_label = APP_LABEL

    # ------------------------------------------------------------------ registry

    @service_method(read_only=False, since="0.1.0")
    def setup(
        self,
        *,
        actor: Any,
        name: str,
        writer_group_ids: tuple[UUID, ...] = (),
        reader_group_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> RegistryInfo:
        """Create the organization's default patient registry and share it with groups.

        Autorização: a capacidade ``access.manage`` (administrador da organização) e ``create`` em
        med_patients.patientregistry.
        Erros: Forbidden sem a capacidade ou a permissão de tabela; InvalidInput para nome vazio,
        chave inválida, mais de 20 grupos ou grupo de outra organização; Conflict("already_set_up")
        quando a organização já tem um cadastro padrão criado com outra chave.
        Efeitos: cria o cadastro (privado, dono o ator), dá ao papel ``member`` leitura e alteração
        da tabela do cadastro, concede leitura e alteração aos grupos de escrita e leitura aos de
        leitura; tudo na transação do chamador. A mesma chave do mesmo ator devolve o cadastro já
        criado, sem repetir concessões.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.access import AccessService
        from skeleton.tenancy.context import current_context

        from .services import deterministic_id

        key = _key(idempotency_key)
        writers = _group_ids(writer_group_ids, "writer_group_ids")
        readers = tuple(group for group in _group_ids(reader_group_ids, "reader_group_ids") if group not in writers)
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 120:
            raise InvalidInput({"name": [gettext("Informe o nome do cadastro (até 120 caracteres).")]})
        _require_access_manager(actor)
        if not has_table_permission(PatientRegistry, user=actor, action="create"):
            raise Forbidden()
        sysid = deterministic_id("registry", actor, key)
        existing = PatientRegistry.objects.filter(pk=sysid).first()
        if existing is not None:
            return registry_info(existing, writable=True)
        if PatientRegistry.objects.filter(is_default=True).exists():
            raise Conflict("already_set_up")
        registry = PatientRegistry(
            sysid=sysid,
            organization_id=current_context().organization_id,
            owner_id=actor.pk,
            visibility=PatientRegistry.Visibility.PRIVATE,
            name=clean_name,
            is_default=True,
        )
        registry.save()
        access = AccessService()
        access.grant_member_table_access(actor=actor, table_key=REGISTRY_TABLE, actions=("read", "update"))
        for group in writers:
            for action in ("read", "update"):
                access.grant_record_access(
                    actor=actor, table_key=REGISTRY_TABLE, record_id=registry.pk, action=action, group_id=group
                )
        for group in readers:
            access.grant_record_access(
                actor=actor, table_key=REGISTRY_TABLE, record_id=registry.pk, action="read", group_id=group
            )
        return registry_info(registry, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def registries(self, *, actor: Any) -> tuple[RegistryInfo, ...]:
        """Patient registries the actor reads, the default one first.

        Autorização: TablePermission read em med_patients.patientregistry e leitura de cada cadastro.
        Erros: Forbidden sem a permissão de tabela; Unavailable com a app desativada.
        Efeitos: nenhum.
        """
        rows = list(readable_registries(actor))
        writable = ids_allowed(writable_registries, actor)
        return tuple(registry_info(row, writable=row.pk in writable) for row in rows)

    # ------------------------------------------------------------------ reading

    @service_method(read_only=True, since="0.1.0")
    def search(
        self,
        *,
        actor: Any,
        query: str = "",
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Page[PatientSummary]:
        """Patients the actor reads, by name order, filtered by a free-text query and a status.

        ``query`` with 11 digits is an exact CPF; ``P`` and digits is a code; 8 or more digits is
        the end of a phone number; anything else matches every word of the name or social name,
        without accents.
        Autorização: leitura do cadastro de cada paciente.
        Erros: InvalidInput para situação desconhecida, cursor ou tamanho de página inválidos;
        Forbidden sem a permissão de tabela do cadastro.
        Efeitos: nenhum.
        """
        from django.db.models import Q

        from .services import search_filter

        rows = readable_patients(actor)
        if status is not None:
            if status not in Patient.Status.values:
                raise InvalidInput({"status": [gettext("Situação desconhecida.")]})
            rows = rows.filter(status=status)
        kind, value = search_filter(query if isinstance(query, str) else "")
        if kind == "cpf":
            rows = rows.filter(cpf=value)
        elif kind == "code":
            rows = rows.filter(code=value)
        elif kind == "phone":
            rows = rows.filter(Q(phone__endswith=value) | Q(phone_secondary__endswith=value))
        else:
            for word in value.split()[:8]:
                rows = rows.filter(search_name__contains=word)
        return paginate(rows, convert=patient_summary, cursor=cursor, page_size=page_size, key=("search_name", "sysid"))

    @service_method(read_only=True, since="0.1.0")
    def get(self, *, actor: Any, patient_id: UUID) -> PatientInfo:
        """Everything the app keeps about one patient.

        Autorização: leitura do cadastro do paciente.
        Erros: NotFound para paciente inexistente, de outra organização ou ilegível (a mesma resposta).
        Efeitos: nenhum.
        """
        patient = _readable(actor, patient_id)
        writable = writable_patients(actor).filter(pk=patient.pk).exists()
        return patient_info(patient, writable=writable)

    @service_method(read_only=True, since="0.1.0")
    def summary(self, *, actor: Any, patient_id: UUID) -> PatientSummary:
        """Code, display name, birth date and status of one patient.

        Autorização: leitura do cadastro do paciente.
        Erros: NotFound para paciente inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        return patient_summary(_readable(actor, patient_id))

    @service_method(read_only=True, since="0.1.0")
    def summaries(self, *, actor: Any, patient_ids: tuple[UUID, ...]) -> tuple[PatientSummary, ...]:
        """Summaries of up to 200 patients, in the order asked; the ones the actor does not read are left out.

        Autorização: leitura do cadastro de cada paciente.
        Erros: InvalidInput para mais de 200 identificadores ou identificador inválido.
        Efeitos: nenhum.
        """
        if not isinstance(patient_ids, tuple) or len(patient_ids) > MAX_SUMMARIES:
            raise InvalidInput({"patient_ids": [gettext("Informe até 200 pacientes.")]})
        wanted = [as_uuid(item, field="patient_ids") for item in patient_ids]
        found = {patient.pk: patient for patient in readable_patients(actor).filter(pk__in=wanted)}
        return tuple(patient_summary(found[pk]) for pk in dict.fromkeys(wanted) if pk in found)

    @service_method(read_only=True, since="0.1.0")
    def find_duplicates(
        self, *, actor: Any, cpf: str = "", full_name: str = "", birth_date: date | None = None
    ) -> tuple[PatientSummary, ...]:
        """Live patients that look like the same person: same CPF, or same name and birth date.

        Autorização: leitura do cadastro de cada paciente.
        Erros: nenhum além do contrato.
        Efeitos: nenhum.
        """
        from django.db.models import Q

        from . import validators

        condition = Q(pk__in=())
        plain = validators.digits(cpf)
        if plain:
            condition |= Q(cpf=plain)
        name = validators.normalize_name(full_name)
        if name and birth_date is not None:
            condition |= Q(search_name__startswith=name, birth_date=birth_date)
        rows = readable_patients(actor).filter(condition).order_by("search_name", "sysid")[:20]
        return tuple(patient_summary(row) for row in rows)

    # ------------------------------------------------------------------ commands

    @service_method(read_only=False, since="0.1.0")
    def create(
        self,
        *,
        actor: Any,
        data: PatientInput,
        registry_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> PatientInfo:
        """Register a patient in a registry (the default one when not given).

        Autorização: alteração (``update``) no cadastro.
        Erros: NotFound para cadastro inexistente ou ilegível; Forbidden se só lê o cadastro;
        InvalidInput com o nome do campo inválido (nunca o valor); Conflict("integrity_conflict")
        para CPF já cadastrado entre os vivos.
        Efeitos: valida tudo, depois tira o código da sequência sem lacunas, grava o paciente e
        publica ``med_patients.patient_created``. A mesma chave do mesmo ator devolve o paciente
        já criado.
        """
        from skeleton.service_api.sequences import SequenceService
        from skeleton.tenancy.context import current_context

        from .registration import PATIENT_SEQUENCE
        from .services import apply_search_name, clean_patient_values, deterministic_id

        if not isinstance(data, PatientInput):
            raise InvalidInput({"data": [gettext("Use PatientInput.")]})
        values = clean_patient_values({field.name: getattr(data, field.name) for field in fields(data)}, partial=False)
        registry = _default_writable_registry(actor, registry_id)
        sysid = None
        if idempotency_key is not None:
            sysid = deterministic_id("patient", actor, _key(idempotency_key))
            existing = readable_patients(actor).filter(pk=sysid).first()
            if existing is not None:
                return patient_info(existing, writable=True)
        number = SequenceService().next_number(actor=actor, key=PATIENT_SEQUENCE)
        patient = Patient(organization_id=current_context().organization_id, registry=registry, code=number.formatted)
        if sysid is not None:
            patient.sysid = sysid
        for name, value in values.items():
            setattr(patient, name, value)
        apply_search_name(patient)
        patient.save()
        _publish(actor, "patient_created", patient)
        return patient_info(patient, writable=True)

    @service_method(read_only=False, since="0.1.0")
    def update(
        self, *, actor: Any, patient_id: UUID, changes: tuple[tuple[str, Scalar], ...], expected_revision: int
    ) -> PatientInfo:
        """Change identification, contact or address fields of a patient, with CAS.

        Accepted fields: those of ``PatientInput``. Code, registry, status, anonymization and the
        processing restriction have their own operations.
        Autorização: alteração no cadastro do paciente.
        Erros: NotFound; Forbidden se só lê; InvalidInput com o nome do campo; Conflict
        ("stale_revision", "processing_restricted", "anonymized", "integrity_conflict").
        Efeitos: grava só os campos que mudaram e publica ``med_patients.patient_updated``; sem
        mudança real, não grava nem publica.
        """
        from .services import apply_search_name, clean_patient_values

        if not isinstance(changes, tuple) or not all(isinstance(item, tuple) and len(item) == 2 for item in changes):
            raise InvalidInput({"changes": [gettext("Use pares (campo, valor).")]})
        values = clean_patient_values(dict(changes), partial=True)
        patient = _writable(actor, patient_id, lock=True)
        _check_revision(patient, expected_revision)
        _require_changeable(patient)
        changed = {name for name, value in values.items() if getattr(patient, name) != value}
        if not changed:
            return patient_info(patient, writable=True)
        for name in changed:
            setattr(patient, name, values[name])
        if changed & {"full_name", "social_name"}:
            apply_search_name(patient)
            changed.add("search_name")
        patient.save(update_fields=changed)
        _publish(actor, "patient_updated", patient)
        return patient_info(patient, writable=True)

    @service_method(read_only=False, since="0.1.0")
    def set_status(
        self,
        *,
        actor: Any,
        patient_id: UUID,
        status: str,
        expected_revision: int,
        deceased_on: date | None = None,
    ) -> PatientInfo:
        """Mark a patient active, inactive or deceased (with the date of death), with CAS.

        Autorização: alteração no cadastro do paciente.
        Erros: NotFound; Forbidden; InvalidInput para situação desconhecida, óbito sem data ou data
        futura; Conflict("stale_revision", "anonymized").
        Efeitos: grava a situação e publica ``med_patients.patient_status_changed``.
        """
        from django.utils import timezone

        if status not in Patient.Status.values:
            raise InvalidInput({"status": [gettext("Situação desconhecida.")]})
        if status == Patient.Status.DECEASED:
            if not isinstance(deceased_on, date) or deceased_on > timezone.localdate():
                raise InvalidInput({"deceased_on": [gettext("Informe a data do óbito, que não pode ser futura.")]})
        else:
            deceased_on = None
        patient = _writable(actor, patient_id, lock=True)
        _check_revision(patient, expected_revision)
        if patient.anonymized_at is not None:
            raise Conflict("anonymized")
        if (patient.status, patient.deceased_on) == (status, deceased_on):
            return patient_info(patient, writable=True)
        patient.status = status
        patient.deceased_on = deceased_on
        patient.save(update_fields={"status", "deceased_on"})
        _publish(actor, "patient_status_changed", patient)
        return patient_info(patient, writable=True)

    @service_method(read_only=False, since="0.1.0")
    def delete(self, *, actor: Any, patient_id: UUID, expected_revision: int) -> None:
        """Delete a patient (tombstone), with CAS; guardians, coverages and consents disappear with it.

        Autorização: alteração no cadastro do paciente.
        Erros: NotFound; Forbidden; Conflict("stale_revision"); Conflict("retention", motivo) quando
        uma guarda de retenção registrada veta; Conflict("live_references") quando registros de
        outras apps ainda apontam para o paciente.
        Efeitos: exclusão lógica; os dados continuam no banco e voltam com ``restore``.
        """
        patient = _writable(actor, patient_id, lock=True)
        _check_revision(patient, expected_revision)
        from .extension import retention_vetoes

        reasons = retention_vetoes(actor=actor, patient=patient)
        if reasons:
            raise Conflict("retention", "; ".join(reasons))
        patient.delete()

    @service_method(read_only=False, since="0.1.0")
    def restore(self, *, actor: Any, patient_id: UUID, expected_revision: int) -> PatientInfo:
        """Bring back a deleted patient with the same identifier, code and data, with CAS.

        Autorização: alteração no cadastro do paciente (o cadastro precisa estar vivo).
        Erros: NotFound para paciente inexistente, vivo-ilegível ou de outra organização;
        Conflict("stale_revision"); Conflict("integrity_conflict") quando o CPF já voltou a ser de
        outro paciente vivo.
        Efeitos: desfaz a exclusão lógica; responsáveis, convênios e consentimentos voltam junto.
        """
        patient = _readable(actor, patient_id, include_deleted=True)
        if patient.deleted_at is None:
            raise NotFound()
        _check_revision(patient, expected_revision)
        patient.restore()
        return patient_info(patient, writable=True)
