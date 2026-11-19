"""The reference app plugs into the four apps through each extension point, without changing them."""

from __future__ import annotations

from django.apps import AppConfig


def _note_from_event(envelope, *, source: str) -> None:
    """Consumer of another app's event: one note per event, in the event's organization (system context)."""
    from .models import ExampleBoard, ExampleNote

    board = ExampleBoard.objects.order_by("created_at").first()
    patient = dict(envelope.data).get("patient")
    if board is None or not patient:
        return
    key = str(envelope.record_sysid)
    if ExampleNote.objects.filter(source=source, source_key=key).exists():
        return
    ExampleNote(
        organization_id=envelope.organization_id,
        board=board,
        patient_id=patient,
        source=source,
        source_key=key,
        text=source,
    ).save()


def on_appointment_completed(envelope) -> None:
    _note_from_event(envelope, source="med_scheduling.appointment_completed")


def on_encounter_signed(envelope) -> None:
    _note_from_event(envelope, source="med_records.encounter_signed")


def _notes_of(*, actor, patient_id, before, limit):
    from applications.med_patients.service_api import TimelineEntry

    from .service_api import ExampleService

    try:
        notes = ExampleService().notes(actor=actor, patient_id=patient_id)
    except Exception:  # noqa: BLE001 - no board: nothing to show
        return ()
    return tuple(
        TimelineEntry(at=_now(), source="med_example.notes", kind="note", title="Nota de exemplo")
        for _note in notes[:limit]
    )


def _now():
    from django.utils import timezone

    return timezone.now()


def _keep(*, patient_id):
    from .models import ExampleNote

    if ExampleNote.objects.filter(patient_id=patient_id, keep=True).exists():
        return "Nota de exemplo marcada para guardar."
    return None


class MedExampleConfig(AppConfig):
    name = __package__
    label = "med_example"
    verbose_name = "Exemplo de extensão"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from pathlib import Path

        from applications.med_finance.service_api import ChargeOrigin, register_charge_origin
        from applications.med_patients.service_api import (
            ConsentPurpose,
            PatientSection,
            SetupStep,
            register_consent_purpose,
            register_patient_data_provider,
            register_patient_section,
            register_retention_guard,
            register_setup_step,
            register_timeline_provider,
        )
        from applications.med_records.service_api import (
            DocumentKind,
            SectionField,
            SectionType,
            register_document_kind,
            register_section_type,
        )
        from applications.med_scheduling.service_api import AppointmentAction, register_appointment_action
        from skeleton.events.registry import register_consumer
        from skeleton.system.app_registry import AppManifest, register_app
        from skeleton.system.registry import TableSpec, register

        from .models import ExampleBoard, ExampleNote

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        register(
            TableSpec(
                model=ExampleBoard,
                description="Quadros de notas de exemplo.",
                read_fields=("name", "owner", "visibility"),
                write_fields=("name",),
                expose_api=True,
            )
        )
        register(
            TableSpec(
                model=ExampleNote,
                description="Notas de exemplo sobre pacientes.",
                read_fields=("board", "patient", "source", "source_key", "text", "keep"),
                write_fields=(),
                sensitive_fields=("text",),
                expose_api=False,
                access_parent="board",
            )
        )
        register_consumer(
            "med_scheduling.appointment_completed", "med_example.note_on_completed", on_appointment_completed
        )
        register_consumer("med_records.encounter_signed", "med_example.note_on_signed", on_encounter_signed)
        register_patient_section(PatientSection("med_example.notes", "Notas", "med_example:notes", order=90))
        register_timeline_provider("med_example.notes", _notes_of)
        register_consent_purpose(ConsentPurpose("med_example.reminders", "Lembretes de exemplo"))
        register_retention_guard("med_example.keep", _keep)
        register_patient_data_provider("med_example.notes", lambda *, actor, patient_id: (("Notas de exemplo", "—"),))
        register_setup_step(SetupStep("med_example.board", "Exemplo", "med_example:notes_home", lambda **kw: True, 90))
        register_appointment_action(
            AppointmentAction("med_example.look", "Ver notas", "med_example:look", statuses=("arrived",), order=90)
        )
        register_section_type(
            SectionType(
                "med_example.eye_exam",
                "Exame oftalmológico de exemplo",
                (SectionField("visual_acuity", "Acuidade visual", "text"),),
            )
        )
        register_document_kind(DocumentKind("med_example.letter", "Carta de exemplo", "Para {{patient_name}}."))
        register_charge_origin(ChargeOrigin("med_example", "Exemplo"))
