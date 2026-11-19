"""Tables, gateway operations, sequences and events of the patients app, registered in ``ready()``."""

from __future__ import annotations

from django.utils.translation import gettext_lazy

APP_LABEL = "med_patients"
PATIENT_SEQUENCE = "med_patients.patient"

PATIENT_READ_FIELDS = (
    "registry",
    "code",
    "full_name",
    "social_name",
    "birth_date",
    "sex",
    "cpf",
    "national_health_card",
    "identity_document",
    "mother_name",
    "phone",
    "phone_secondary",
    "email",
    "contact_preference",
    "postal_code",
    "street",
    "number",
    "complement",
    "district",
    "city",
    "state",
    "status",
    "deceased_on",
    "notes",
    "processing_restricted",
    "anonymized_at",
)
# Identification, contact, address and notes: readable by who reads the registry, redacted in the audit.
PATIENT_PERSONAL_FIELDS = (
    "full_name",
    "social_name",
    "search_name",
    "birth_date",
    "sex",
    "cpf",
    "national_health_card",
    "identity_document",
    "mother_name",
    "phone",
    "phone_secondary",
    "email",
    "postal_code",
    "street",
    "number",
    "complement",
    "district",
    "city",
    "state",
    "deceased_on",
    "notes",
)


def register_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import TableSpec, register

    from . import services
    from .models import Patient, PatientRegistry

    register(
        TableSpec(
            model=PatientRegistry,
            description=gettext_lazy("Cadastros de pacientes da clínica; quem altera o cadastro altera os pacientes."),
            label=gettext_lazy("Cadastros de pacientes"),
            scope="organization",
            read_fields=("name", "is_default", "owner", "visibility"),
            write_fields=("name",),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    # Through the generic gateway a registry is only renamed: it is born by setup and never deleted there.
    register_record_operations("med_patients.patientregistry", RecordOperations(update=services.update_registry_record))
    register(
        TableSpec(
            model=Patient,
            description=gettext_lazy("Pacientes do cadastro; a autorização vem do cadastro."),
            label=gettext_lazy("Pacientes"),
            scope="organization",
            read_fields=PATIENT_READ_FIELDS,
            write_fields=(),
            sensitive_fields=(),
            personal_fields=PATIENT_PERSONAL_FIELDS,
            expose_api=False,
            access_parent="registry",
        )
    )


EVENT_PAYLOAD = ("code", "status", "registry")
PATIENT_EVENTS = ("patient_created", "patient_updated", "patient_status_changed")


def register_sequences_and_events() -> None:
    from skeleton.events.registry import EventType, register_event_type
    from skeleton.sequences.registry import SequenceSpec, register_sequence

    register_sequence(SequenceSpec(key=PATIENT_SEQUENCE, period="none", template="P{number:06d}", owner_app=APP_LABEL))
    for name in PATIENT_EVENTS:
        register_event_type(
            EventType(
                code=f"{APP_LABEL}.{name}",
                table_key="med_patients.patient",
                payload_fields=EVENT_PAYLOAD,
                owner_app=APP_LABEL,
            )
        )


def register_patient_rows() -> None:
    """Guardians and coverages: derived from the patient (two hops to the registry)."""
    from skeleton.system.registry import TableSpec, register

    from .models import PatientCoverage, PatientGuardian

    register(
        TableSpec(
            model=PatientGuardian,
            description=gettext_lazy("Responsáveis e contatos dos pacientes; a autorização vem do cadastro."),
            label=gettext_lazy("Responsáveis"),
            scope="organization",
            read_fields=(
                "patient",
                "name",
                "relationship",
                "cpf",
                "phone",
                "email",
                "is_legal_representative",
                "is_financial_responsible",
                "notes",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("name", "cpf", "phone", "email", "notes"),
            expose_api=False,
            access_parent="patient",
        )
    )
    register(
        TableSpec(
            model=PatientCoverage,
            description=gettext_lazy("Convênios dos pacientes; a autorização vem do cadastro."),
            label=gettext_lazy("Convênios"),
            scope="organization",
            read_fields=(
                "patient",
                "insurer_name",
                "insurer_code",
                "plan_name",
                "card_number",
                "holder_name",
                "valid_until",
                "is_primary",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("card_number", "holder_name"),
            expose_api=False,
            access_parent="patient",
        )
    )


CONSENT_TERM_TYPES = ("application/pdf", "image/jpeg", "image/png")
CONSENT_TERM_MAX_BYTES = 10 * 1024 * 1024


def register_consents() -> None:
    from django.utils.translation import gettext_lazy as _

    from skeleton.events.registry import EventType, register_event_type
    from skeleton.system.registry import AttachmentPolicy, TableSpec, register

    from .extension import ConsentPurpose, register_consent_purpose
    from .models import Consent

    register(
        TableSpec(
            model=Consent,
            description=_("Consentimentos dos pacientes por finalidade; o termo digitalizado vai anexo."),
            label=_("Consentimentos"),
            scope="organization",
            read_fields=(
                "patient",
                "purpose",
                "status",
                "granted_at",
                "revoked_at",
                "collected_via",
                "term_version",
                "evidence_note",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("evidence_note",),
            expose_api=False,
            access_parent="patient",
            attachments=AttachmentPolicy(max_bytes=CONSENT_TERM_MAX_BYTES, types=CONSENT_TERM_TYPES),
        )
    )
    register_event_type(
        EventType(
            code=f"{APP_LABEL}.consent_changed",
            table_key="med_patients.consent",
            payload_fields=("patient", "purpose", "status"),
            owner_app=APP_LABEL,
        )
    )
    register_consent_purpose(
        ConsentPurpose(
            code="med_patients.contact",
            label=_("Contato com o paciente"),
            description=_("Contato por telefone, mensagem e email para assuntos do atendimento."),
        )
    )


IMPORT_TYPES = ("text/csv", "text/plain")
IMPORT_MAX_BYTES = 10 * 1024 * 1024


def register_imports() -> None:
    from django.utils.translation import gettext_lazy as _

    from skeleton.jobs.registry import JobType, register_job_type
    from skeleton.system.registry import AttachmentPolicy, TableSpec, register

    from . import jobs
    from .models import ImportBatch

    register(
        TableSpec(
            model=ImportBatch,
            description=_("Importações de pacientes por CSV; a autorização vem do cadastro."),
            label=_("Importações de pacientes"),
            scope="organization",
            read_fields=(
                "registry",
                "status",
                "filename",
                "columns",
                "mapping",
                "total_rows",
                "valid_rows",
                "applied_rows",
                "created_rows",
                "skipped_rows",
                "error_rows",
                "report",
                "error_code",
                "finished_at",
            ),
            write_fields=(),
            sensitive_fields=(),
            # The decoded file carries the patients' data until the batch ends.
            personal_fields=("content",),
            expose_api=False,
            access_parent="registry",
            attachments=AttachmentPolicy(max_bytes=IMPORT_MAX_BYTES, types=IMPORT_TYPES),
        )
    )
    for code, handler in (
        (jobs.VALIDATE_JOB, jobs.validate_batch),
        (jobs.APPLY_JOB, jobs.apply_batch),
    ):
        register_job_type(
            JobType(
                code=code,
                handler=handler,
                payload_schema={"batch_id": "uuid"},
                run_as="actor",
                max_attempts=3,
                timeout_s=600,
                owner_app=APP_LABEL,
            )
        )


def register_setup_steps() -> None:
    """The first step of the clinic setup list: the patient registry."""
    from django.utils.translation import gettext_lazy

    from .extension import SetupStep, register_setup_step

    register_setup_step(
        SetupStep("med_patients.registry", gettext_lazy("Pacientes"), "med_patients:setup", _has_registry, order=10)
    )


def _has_registry(*, actor) -> bool:
    from .service_api import PatientService

    return bool(PatientService().registries(actor=actor))


def register_quota_metrics() -> None:
    """The number of active patients: measured for the plans, never limited by this app."""
    from skeleton.service_api.billing import register_quota_metric

    register_quota_metric("med_patients.active_patients", count_active_patients)


def count_active_patients(organization_id) -> int:
    from .models import Patient

    return Patient.objects.filter(organization_id=organization_id, status="active").count()
