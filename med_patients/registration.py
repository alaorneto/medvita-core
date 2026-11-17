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
