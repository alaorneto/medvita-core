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
            description=_("Tipos de atendimento do consultório: duração, cor e código de cobrança."),
            label=_("Tipos de atendimento"),
            scope="organization",
            read_fields=(
                "practice",
                "code",
                "name",
                "duration_minutes",
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

    from .models import AvailabilityRule, Schedule, ScheduleBlock

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
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="schedule",
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
