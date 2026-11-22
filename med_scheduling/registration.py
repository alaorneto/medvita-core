"""Tables, gateway operations, sequences, events and jobs of the scheduling app, registered in ``ready()``."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

APP_LABEL = "med_scheduling"


def _practice_update(record, *, user, values):
    """Generic gateway update of the practice: only the establishment fields."""
    for name, value in values.items():
        setattr(record, name, value)
    record.save(update_fields=set(values))


def register_practice_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import TableSpec, register

    from .models import AppointmentType, Practice, Professional, Room

    register(
        TableSpec(
            model=Practice,
            description=_("Consultórios: dados do estabelecimento e a configuração de profissionais, salas e tipos."),
            label=_("Consultórios"),
            scope="organization",
            read_fields=(
                "name",
                "legal_name",
                "tax_id",
                "phone",
                "email",
                "address",
                "city",
                "state",
                "timezone",
                "is_default",
                "owner",
                "visibility",
            ),
            write_fields=("name", "legal_name", "phone", "email", "address", "city", "state"),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    register_record_operations("med_scheduling.practice", RecordOperations(update=_practice_update))
    register(
        TableSpec(
            model=Professional,
            description=_("Profissionais de saúde do consultório; a autorização vem do consultório."),
            label=_("Profissionais"),
            scope="organization",
            read_fields=(
                "practice",
                "user",
                "display_name",
                "council",
                "council_number",
                "council_state",
                "specialty",
                "rqe",
                "tax_id",
                "is_active",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("display_name", "council_number", "tax_id"),
            expose_api=False,
            access_parent="practice",
        )
    )
    register(
        TableSpec(
            model=Room,
            description=_("Salas e equipamentos do consultório."),
            label=_("Salas"),
            scope="organization",
            read_fields=("practice", "name", "kind", "is_active"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="practice",
        )
    )
    register(
        TableSpec(
            model=AppointmentType,
            description=_("Tipos de atendimento do consultório: duração, forma de pagamento, cor e cobrança."),
            label=_("Tipos de atendimento"),
            scope="organization",
            read_fields=(
                "practice",
                "code",
                "name",
                "duration_minutes",
                "payment_kind",
                "color",
                "billing_code",
                "requires_room",
                "is_active",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="practice",
        )
    )


def register_schedule_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import TableSpec, register

    from .models import AvailabilityRule, AvailabilityRuleType, Schedule, ScheduleAppointmentType, ScheduleBlock

    register(
        TableSpec(
            model=Schedule,
            description=_(
                "Agendas de profissionais, salas e equipamentos; cada uma projeta as consultas num calendário."
            ),
            label=_("Agendas"),
            scope="organization",
            read_fields=(
                "practice",
                "name",
                "professional",
                "room",
                "calendar",
                "slot_minutes",
                "booking_horizon_days",
                "is_active",
                "owner",
                "visibility",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    # Schedules are created and shared only by SchedulingService (the calendar mirror depends on it).
    register_record_operations("med_scheduling.schedule", RecordOperations())
    register(
        TableSpec(
            model=ScheduleAppointmentType,
            description=_("Tipos de atendimento que cada agenda atende, com a duração própria da agenda."),
            label=_("Tipos da agenda"),
            scope="organization",
            read_fields=("schedule", "appointment_type", "duration_minutes", "allow_booked", "allow_walk_in"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="schedule",
        )
    )
    register(
        TableSpec(
            model=AvailabilityRule,
            description=_("Grade semanal de cada agenda."),
            label=_("Grade de horários"),
            scope="organization",
            read_fields=(
                "schedule",
                "weekday",
                "start_minute",
                "end_minute",
                "valid_from",
                "valid_until",
                "appointment_type",
                "mode",
                "capacity",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="schedule",
        )
    )
    register(
        TableSpec(
            model=AvailabilityRuleType,
            description=_("Tipos de atendimento que cada período da grade semanal atende."),
            label=_("Tipos do período"),
            scope="organization",
            read_fields=("rule", "appointment_type"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="rule",
        )
    )
    register(
        TableSpec(
            model=ScheduleBlock,
            description=_("Bloqueios das agendas: férias, feriados, reuniões."),
            label=_("Bloqueios"),
            scope="organization",
            read_fields=("schedule", "starts_at", "ends_at", "reason", "note"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="schedule",
        )
    )


APPOINTMENT_SEQUENCE = "med_scheduling.appointment"
APPOINTMENT_EVENTS = ("booked", "rescheduled", "confirmed", "arrived", "started", "completed", "no_show", "cancelled")
APPOINTMENT_PAYLOAD = (
    "code",
    "schedule",
    "patient",
    "appointment_type",
    "billing_code",
    "starts_at",
    "ends_at",
    "status",
    "mode",
)


def register_appointments() -> None:
    from skeleton.events.registry import EventType, register_event_type
    from skeleton.sequences.registry import SequenceSpec, register_sequence
    from skeleton.system.registry import TableSpec, register

    from .models import Appointment

    register(
        TableSpec(
            model=Appointment,
            description=_("Consultas das agendas; as observações são sensíveis e nunca saem em eventos."),
            label=_("Consultas"),
            scope="organization",
            read_fields=(
                "schedule",
                "code",
                "patient",
                "appointment_type",
                "professional",
                "room",
                "starts_at",
                "ends_at",
                "status",
                "is_fit_in",
                "billing_code",
                "payment_kind",
                "notes",
                "confirmed_at",
                "arrived_at",
                "started_at",
                "completed_at",
                "cancelled_at",
                "cancel_reason",
                "cancel_note",
                "rescheduled_from",
                "mode",
                "duration_minutes",
                "arrival_number",
                "is_priority",
            ),
            write_fields=(),
            # The priority mark lets one infer age, pregnancy or disability: it never leaves in an event.
            sensitive_fields=("notes", "cancel_note", "is_priority"),
            expose_api=False,
            access_parent="schedule",
        )
    )
    register_sequence(
        SequenceSpec(key=APPOINTMENT_SEQUENCE, period="none", template="A{number:07d}", owner_app=APP_LABEL)
    )
    for name in APPOINTMENT_EVENTS:
        register_event_type(
            EventType(
                code=f"{APP_LABEL}.appointment_{name}",
                table_key="med_scheduling.appointment",
                payload_fields=APPOINTMENT_PAYLOAD,
                owner_app=APP_LABEL,
            )
        )


ARRIVAL_NOTIFICATION = "med_scheduling.patient_arrived"


def register_notifications() -> None:
    from skeleton.notifications.registry import NotificationType, register_notification_type

    register_notification_type(
        NotificationType(
            code=ARRIVAL_NOTIFICATION,
            label="Paciente chegou",  # A plain string: the core inbox returns it as is.
            payload_fields=("code", "starts_at"),
            target_table_key="med_scheduling.appointment",
            owner_app=APP_LABEL,
            group_key="arrived:{target}",
        )
    )


EXPIRE_WAITLIST_JOB = "med_scheduling.expire_waitlist"


def register_waitlist() -> None:
    from datetime import time

    from skeleton.jobs.periodic import register_periodic
    from skeleton.jobs.registry import JobType, register_job_type
    from skeleton.system.registry import TableSpec, register

    from . import jobs
    from .models import WaitlistEntry

    register(
        TableSpec(
            model=WaitlistEntry,
            description=_("Lista de espera do consultório; a observação é sensível."),
            label=_("Lista de espera"),
            scope="organization",
            read_fields=(
                "practice",
                "patient",
                "appointment_type",
                "schedule",
                "preferred_period",
                "earliest_date",
                "latest_date",
                "priority",
                "status",
                "note",
                "booked_appointment",
            ),
            write_fields=(),
            sensitive_fields=("note",),
            expose_api=False,
            access_parent="practice",
        )
    )
    register_job_type(
        JobType(code=EXPIRE_WAITLIST_JOB, handler=jobs.expire_waitlist, run_as="system", owner_app=APP_LABEL)
    )
    register_periodic(EXPIRE_WAITLIST_JOB, EXPIRE_WAITLIST_JOB, daily_at=time(6, 17))


def register_quota_metrics() -> None:
    """The number of active professionals, a metric a plan of the platform billing can limit."""
    from skeleton.service_api.billing import register_quota_metric

    register_quota_metric("med_scheduling.active_professionals", count_active_professionals)


def count_active_professionals(organization_id) -> int:
    from .models import Professional

    return Professional.objects.filter(organization_id=organization_id, is_active=True).count()


def register_token_scopes() -> None:
    """Named scopes of the REST API (#61); a broad OIDC token carries them too, the role still decides."""
    from skeleton.integrations.tokens.scopes import register_token_scope

    from .api_support import SCOPE_READ, SCOPE_WRITE

    register_token_scope(SCOPE_READ, _("Ler agendas, horários livres e consultas pela API"))
    register_token_scope(SCOPE_WRITE, _("Marcar consultas e mudar a situação delas pela API"))
