"""Tables, sequences, events and contributions of the records app, registered in ``ready()``."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

APP_LABEL = "med_records"


def _archive_update(record, *, user, values):
    """Generic gateway update of an archive: only its name."""
    for name, value in values.items():
        setattr(record, name, value)
    record.save(update_fields=set(values))


def register_archive_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import TableSpec, register

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
        )
    )


def register_contributions() -> None:
    """The retention guard and the setup step offered by the patients app."""
    from applications.med_patients.service_api import SetupStep, register_retention_guard, register_setup_step

    from .retention import retention_guard

    register_retention_guard("med_records.retention", retention_guard)
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
