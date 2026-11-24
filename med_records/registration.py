"""Tables, sequences, events and contributions of the records app, registered in ``ready()``."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

APP_LABEL = "med_records"
# Exams and external documents attached to a chart or an encounter.
ATTACHMENT_TYPES = ("application/pdf", "image/jpeg", "image/png")
ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024


def _archive_update(record, *, user, values):
    """Generic gateway update of an archive: only its name."""
    for name, value in values.items():
        setattr(record, name, value)
    record.save(update_fields=set(values))


def register_archive_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import AttachmentPolicy, TableSpec, register

    from .models import Archive, PatientChart

    register(
        TableSpec(
            model=Archive,
            description=_("Arquivos clínicos: quem lê um arquivo lê os prontuários dele."),
            label=_("Arquivos clínicos"),
            scope="organization",
            read_fields=("name", "kind", "is_default", "owner", "visibility"),
            write_fields=("name",),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    register_record_operations("med_records.archive", RecordOperations(update=_archive_update))
    register(
        TableSpec(
            model=PatientChart,
            description=_("Prontuário de um paciente num arquivo clínico; a autorização vem do arquivo."),
            label=_("Prontuários"),
            scope="organization",
            read_fields=("archive", "patient", "opened_at", "last_entry_at"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="archive",
            attachments=AttachmentPolicy(max_bytes=ATTACHMENT_MAX_BYTES, types=ATTACHMENT_TYPES),
        )
    )


def register_contributions() -> None:
    """The retention guard and the setup step offered by the patients app."""
    from applications.med_patients.service_api import SetupStep, register_retention_guard, register_setup_step

    from .retention import retention_guard

    register_retention_guard("med_records.retention", retention_guard)
    from applications.med_scheduling.service_api import AppointmentAction, register_appointment_action

    register_appointment_action(
        AppointmentAction(
            "med_records.attend",
            _("Atender"),
            "med_records:attend",
            statuses=("arrived", "in_progress"),
            order=10,
            icon="encounter",
        )
    )
    register_setup_step(SetupStep("med_records.archives", _("Prontuário"), "med_records:setup", _has_archive, order=30))


def _has_archive(*, actor) -> bool:
    from .service_api import RecordsService

    return bool(RecordsService().archives(actor=actor))


def register_clinical_types() -> None:
    """The seven basic section types and the five basic document kinds of the app."""
    from .documents import BASIC_KINDS
    from .extension import register_document_kind, register_section_type
    from .sections import BASIC_TYPES

    for section_type in BASIC_TYPES:
        register_section_type(section_type)
    for kind in BASIC_KINDS:
        register_document_kind(kind)


ENCOUNTER_SEQUENCE = "med_records.encounter"


def register_encounters() -> None:
    from skeleton.sequences.registry import SequenceSpec, register_sequence
    from skeleton.system.registry import AttachmentPolicy, SealPolicy, TableSpec, register

    from .models import Encounter, EncounterSection

    register(
        TableSpec(
            model=Encounter,
            description=_("Atendimentos do prontuário: rascunho do autor até a assinatura, que os sela."),
            label=_("Atendimentos"),
            scope="organization",
            read_fields=(
                "chart",
                "patient",
                "code",
                "kind",
                "occurred_at",
                "author",
                "author_name",
                "author_council",
                "appointment",
                "amends",
                "seal_digest",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("author_name", "author_council"),
            expose_api=False,
            access_parent="chart",
            attachments=AttachmentPolicy(max_bytes=ATTACHMENT_MAX_BYTES, types=ATTACHMENT_TYPES),
            seal=SealPolicy(attachments="frozen", comments="frozen"),
        )
    )
    register(
        TableSpec(
            model=EncounterSection,
            description=_("Seções estruturadas dos atendimentos; o conteúdo é dado de saúde."),
            label=_("Seções de atendimento"),
            scope="organization",
            read_fields=("encounter", "section_type", "type_version", "position", "data", "text"),
            write_fields=(),
            sensitive_fields=("data", "text"),
            expose_api=False,
            access_parent="encounter",
        )
    )
    register_sequence(
        SequenceSpec(key=ENCOUNTER_SEQUENCE, period="none", template="E{number:08d}", owner_app=APP_LABEL)
    )
    from skeleton.events.registry import EventType, register_event_type

    register_event_type(
        EventType(
            code="med_records.encounter_signed",
            table_key="med_records.encounter",
            payload_fields=("code", "chart", "patient", "kind", "occurred_at", "seal_digest"),
            owner_app=APP_LABEL,
        )
    )
    from .models import EncounterConsumption

    register(
        TableSpec(
            model=EncounterConsumption,
            description=_(
                "Itens de outras apps consumidos nos atendimentos (material, medicamento, vacina); "
                "a descrição é dado de saúde."
            ),
            label=_("Itens consumidos"),
            scope="organization",
            read_fields=("encounter", "provider", "item_ref", "item_label", "unit", "quantity", "lot"),
            write_fields=(),
            sensitive_fields=("item_label",),
            expose_api=False,
            access_parent="encounter",
        )
    )
    register_event_type(
        EventType(
            code="med_records.items_consumed",
            table_key="med_records.encounterconsumption",
            payload_fields=("encounter", "provider", "item_ref", "quantity", "lot"),
            owner_app=APP_LABEL,
        )
    )


def register_clinical_lists() -> None:
    from skeleton.system.registry import TableSpec, register

    from .models import Allergy, Medication

    register(
        TableSpec(
            model=Allergy,
            description=_("Alergias e intolerâncias do paciente no prontuário; substância e reação são dado de saúde."),
            label=_("Alergias"),
            scope="organization",
            read_fields=("chart", "substance", "category", "reaction", "severity", "status", "noted_on"),
            write_fields=(),
            sensitive_fields=("substance", "reaction"),
            expose_api=False,
            access_parent="chart",
        )
    )
    register(
        TableSpec(
            model=Medication,
            description=_("Medicamentos em uso do paciente no prontuário; são dado de saúde."),
            label=_("Medicamentos em uso"),
            scope="organization",
            read_fields=(
                "chart",
                "name",
                "dose",
                "route",
                "frequency",
                "started_on",
                "ended_on",
                "status",
                "note",
            ),
            write_fields=(),
            sensitive_fields=("name", "dose", "frequency", "note"),
            expose_api=False,
            access_parent="chart",
        )
    )


def register_icd10() -> None:
    from skeleton.system.registry import TableSpec, register

    from .models import Icd10Code

    register(
        TableSpec(
            model=Icd10Code,
            description=_("Tabela CID-10 de referência, global, carregada pelo operador com load_icd10."),
            label=_("CID-10"),
            scope="global",
            read_fields=("code", "description", "is_category"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
        )
    )


DOCUMENT_SEQUENCE = "med_records.document"


def register_documents() -> None:
    from skeleton.events.registry import EventType, register_event_type
    from skeleton.sequences.registry import SequenceSpec, register_sequence
    from skeleton.system.registry import SealPolicy, TableSpec, register

    from .models import ClinicalDocument, EntryTemplate

    register(
        TableSpec(
            model=EntryTemplate,
            description=_("Modelos de atendimento e de documento do arquivo clínico; com autor, são pessoais."),
            label=_("Modelos"),
            scope="organization",
            read_fields=(
                "archive",
                "name",
                "specialty",
                "kind",
                "sections",
                "document_kind",
                "body",
                "author",
                "is_active",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="archive",
        )
    )
    register(
        TableSpec(
            model=ClinicalDocument,
            description=_("Documentos clínicos simples; o texto é dado de saúde e o documento emitido é selado."),
            label=_("Documentos clínicos"),
            scope="organization",
            read_fields=(
                "chart",
                "patient",
                "code",
                "kind",
                "title",
                "body",
                "issued_at",
                "author",
                "author_name",
                "author_council",
                "encounter",
                "replaces",
                "seal_digest",
            ),
            write_fields=(),
            sensitive_fields=("title", "body"),
            personal_fields=("author_name", "author_council"),
            expose_api=False,
            access_parent="chart",
            seal=SealPolicy(attachments="frozen", comments="frozen"),
        )
    )
    register_sequence(SequenceSpec(key=DOCUMENT_SEQUENCE, period="none", template="D{number:08d}", owner_app=APP_LABEL))
    register_event_type(
        EventType(
            code="med_records.document_issued",
            table_key="med_records.clinicaldocument",
            payload_fields=("code", "chart", "patient", "kind", "seal_digest"),
            owner_app=APP_LABEL,
        )
    )


def register_access_log() -> None:
    from skeleton.system.registry import TableSpec, register

    from .models import AccessLog

    register(
        TableSpec(
            model=AccessLog,
            description=_("Trilha de leitura do prontuário: quem leu conteúdo clínico, o quê, quando e de onde."),
            label=_("Trilha de leitura"),
            scope="organization",
            read_fields=("chart", "actor", "action", "target_table", "target_id", "at", "origin", "client_id"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="chart",
        )
    )


def register_token_scopes() -> None:
    """The named scope of the read-only REST API (#61); clinical writing has no scope, it stays on the pages."""
    from skeleton.integrations.tokens.scopes import register_token_scope

    from .api_support import SCOPE_READ

    register_token_scope(SCOPE_READ, _("Ler prontuários, atendimentos e documentos pela API"))
