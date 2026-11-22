"""Tables of the scheduling app (docs/spec.md, "Modelo de dados").

Two containers decide access: ``Practice`` (the clinic and its configuration) and ``Schedule``
(the agenda of a professional, room or piece of equipment). Every other table is derived from one
of them (``TableSpec.access_parent``).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy

from skeleton.common.models import OrganizationRecord, SecuredRecord

COLORS = ("blue", "green", "amber", "red", "purple", "teal", "gray", "pink")


class PaymentKind(models.TextChoices):
    """How an appointment is paid for: the kind of appointment says it, the appointment keeps its copy."""

    PRIVATE = "private", gettext_lazy("Particular")
    INSURANCE = "insurance", gettext_lazy("Convênio")
    COURTESY = "courtesy", gettext_lazy("Cortesia")


def validate_timezone(value: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(gettext("Fuso horário desconhecido.")) from None


class Practice(SecuredRecord):
    """The clinic: establishment data and the configuration every schedule shares."""

    name = models.CharField(max_length=120)
    legal_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=14, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo", validators=[validate_timezone])
    is_default = models.BooleanField(default=False)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_scheduling_one_default_practice",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(tax_id__regex=r"^([0-9]{11}|[0-9]{14})?$"), name="med_scheduling_practice_tax_id"
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class Professional(OrganizationRecord):
    """A health professional of the practice, optionally linked to a member of the organization."""

    class Council(models.TextChoices):
        CRM = "crm", "CRM"
        CRO = "cro", "CRO"
        CRP = "crp", "CRP"
        COREN = "coren", "COREN"
        CREFITO = "crefito", "CREFITO"
        CRN = "crn", "CRN"
        CRFA = "crfa", "CRFa"
        OTHER = "other", gettext_lazy("Outro")

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    display_name = models.CharField(max_length=200)
    council = models.CharField(max_length=10, choices=Council.choices, default=Council.CRM)
    council_number = models.CharField(max_length=20, blank=True)
    council_state = models.CharField(max_length=2, blank=True)
    specialty = models.CharField(max_length=120, blank=True)
    rqe = models.CharField(max_length=20, blank=True)
    tax_id = models.CharField(max_length=11, blank=True)
    is_active = models.BooleanField(default=True)
    immutable_fields = ("practice_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("practice", "user"),
                condition=Q(deleted_at__isnull=True, user__isnull=False),
                name="med_scheduling_one_professional_per_member",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(tax_id__regex=r"^([0-9]{11})?$"), name="med_scheduling_professional_tax_id"
            ),
        ]
        ordering = ("display_name", "sysid")

    @property
    def council_label(self) -> str:
        """``CRM-SP 123456``: what documents and receipts print."""
        if not self.council_number:
            return ""
        state = f"-{self.council_state}" if self.council_state else ""
        return f"{self.get_council_display()}{state} {self.council_number}"


class Room(OrganizationRecord):
    class Kind(models.TextChoices):
        ROOM = "room", gettext_lazy("Sala")
        EQUIPMENT = "equipment", gettext_lazy("Equipamento")

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ROOM)
    is_active = models.BooleanField(default=True)
    immutable_fields = ("practice_id",)

    class Meta(OrganizationRecord.Meta):
        ordering = ("name", "sysid")


class AppointmentType(OrganizationRecord):
    """A kind of appointment: duration, payment, color and the opaque billing code finance resolves.

    "Particular", "Convênio X" and "Retorno Convênio X" are kinds: each one carries how it is paid for.
    """

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    payment_kind = models.CharField(max_length=12, choices=PaymentKind.choices, default=PaymentKind.PRIVATE)
    color = models.CharField(max_length=10, default="blue")
    billing_code = models.CharField(max_length=40, blank=True)
    requires_room = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    immutable_fields = ("practice_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("practice", "code"),
                condition=Q(deleted_at__isnull=True),
                name="med_scheduling_type_live_code",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__gte=5, duration_minutes__lte=480), name="med_scheduling_type_duration"
            ),
            models.CheckConstraint(condition=Q(color__in=COLORS), name="med_scheduling_type_color"),
            models.CheckConstraint(
                condition=Q(payment_kind__in=("private", "insurance", "courtesy")),
                name="med_scheduling_type_payment_kind",
            ),
        ]
        ordering = ("name", "sysid")


class Schedule(SecuredRecord):
    """The agenda of a professional, a room or a piece of equipment, mirrored by a core calendar.

    ``writer_groups``, ``reader_groups`` and ``writer_users`` record the access the schedule was
    shared with; ``SchedulingService.set_schedule_access`` keeps the schedule and its calendar equal.
    """

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    professional = models.ForeignKey(Professional, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    calendar = models.ForeignKey("skeleton_calendar.Calendar", on_delete=models.PROTECT, related_name="+")
    slot_minutes = models.PositiveSmallIntegerField(default=30)
    booking_horizon_days = models.PositiveSmallIntegerField(default=180)
    is_active = models.BooleanField(default=True)
    writer_groups = models.JSONField(default=list, blank=True)
    reader_groups = models.JSONField(default=list, blank=True)
    writer_users = models.JSONField(default=list, blank=True)
    immutable_fields = ("practice_id", "calendar_id")

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(professional__isnull=False) | Q(room__isnull=False), name="med_scheduling_schedule_target"
            ),
            models.CheckConstraint(
                condition=Q(slot_minutes__gte=5, slot_minutes__lte=120), name="med_scheduling_schedule_slot"
            ),
            models.CheckConstraint(
                condition=Q(booking_horizon_days__gte=1, booking_horizon_days__lte=730),
                name="med_scheduling_schedule_horizon",
            ),
        ]
        ordering = ("name", "sysid")

    def __str__(self) -> str:
        return self.name


class ScheduleAppointmentType(OrganizationRecord):
    """A kind of appointment one schedule takes: its own duration there and the modes it is taken in.

    A schedule with no live row takes every active kind of the practice, with the duration of the kind.
    """

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="+")
    appointment_type = models.ForeignKey(AppointmentType, on_delete=models.PROTECT, related_name="+")
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)  # None: the duration of the kind
    allow_booked = models.BooleanField(default=True)
    allow_walk_in = models.BooleanField(default=True)
    immutable_fields = ("schedule_id", "appointment_type_id")

    class Meta(OrganizationRecord.Meta):
        # A short table name: the names the core derives from it must fit PostgreSQL's 63 bytes.
        db_table = "med_scheduling_schedule_type"
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("schedule", "appointment_type"),
                condition=Q(deleted_at__isnull=True),
                name="med_scheduling_schedule_type_live",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__isnull=True) | Q(duration_minutes__gte=5, duration_minutes__lte=480),
                name="med_scheduling_schedule_type_duration",
            ),
            models.CheckConstraint(
                condition=Q(allow_booked=True) | Q(allow_walk_in=True), name="med_scheduling_schedule_type_mode"
            ),
        ]
        ordering = ("schedule", "appointment_type", "sysid")


class AvailabilityRule(OrganizationRecord):
    """A weekly working window of a schedule, in minutes of the day of the practice's time zone."""

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="+")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday ... 6 = Sunday
    start_minute = models.PositiveSmallIntegerField()
    end_minute = models.PositiveSmallIntegerField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    appointment_type = models.ForeignKey(
        AppointmentType, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    immutable_fields = ("schedule_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(condition=Q(weekday__lte=6), name="med_scheduling_rule_weekday"),
            models.CheckConstraint(
                condition=Q(start_minute__lt=models.F("end_minute"), end_minute__lte=1440),
                name="med_scheduling_rule_window",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="med_scheduling_rule_validity",
            ),
        ]
        ordering = ("weekday", "start_minute", "sysid")


class AvailabilityRuleType(OrganizationRecord):
    """A kind of appointment a weekly window takes.

    A window with no live row (and no ``appointment_type`` of its own, the older way of naming a
    single kind) takes every kind the schedule takes.
    """

    rule = models.ForeignKey(AvailabilityRule, on_delete=models.PROTECT, related_name="+")
    appointment_type = models.ForeignKey(AppointmentType, on_delete=models.PROTECT, related_name="+")
    immutable_fields = ("rule_id", "appointment_type_id")

    class Meta(OrganizationRecord.Meta):
        # A short table name: the names the core derives from it must fit PostgreSQL's 63 bytes.
        db_table = "med_scheduling_rule_type"
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("rule", "appointment_type"),
                condition=Q(deleted_at__isnull=True),
                name="med_scheduling_rule_type_live",
                violation_error_code="unique",
            ),
        ]
        ordering = ("rule", "appointment_type", "sysid")


class ScheduleBlock(OrganizationRecord):
    """A period in which the schedule takes no appointment (vacation, holiday, meeting)."""

    class Reason(models.TextChoices):
        VACATION = "vacation", gettext_lazy("Férias")
        HOLIDAY = "holiday", gettext_lazy("Feriado")
        MEETING = "meeting", gettext_lazy("Reunião")
        PERSONAL = "personal", gettext_lazy("Compromisso pessoal")
        OTHER = "other", gettext_lazy("Outro")

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="+")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=12, choices=Reason.choices, default=Reason.OTHER)
    note = models.CharField(max_length=200, blank=True)
    immutable_fields = ("schedule_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(condition=Q(starts_at__lt=models.F("ends_at")), name="med_scheduling_block_window"),
        ]
        ordering = ("starts_at", "sysid")


class Appointment(OrganizationRecord):
    """An appointment of a patient in a schedule; its state changes only through ``transitions.py``."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", gettext_lazy("Agendada")
        CONFIRMED = "confirmed", gettext_lazy("Confirmada")
        ARRIVED = "arrived", gettext_lazy("Paciente chegou")
        IN_PROGRESS = "in_progress", gettext_lazy("Em atendimento")
        COMPLETED = "completed", gettext_lazy("Realizada")
        NO_SHOW = "no_show", gettext_lazy("Falta")
        CANCELLED = "cancelled", gettext_lazy("Cancelada")

    PaymentKind = PaymentKind  # Kept under its first name: the choices now belong to the module.

    class CancelReason(models.TextChoices):
        PATIENT = "patient", gettext_lazy("Pedido do paciente")
        PROFESSIONAL = "professional", gettext_lazy("Pedido do profissional")
        CLINIC = "clinic", gettext_lazy("Pedido da clínica")
        RESCHEDULED = "rescheduled", gettext_lazy("Remarcada")
        OTHER = "other", gettext_lazy("Outro")

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    patient = models.ForeignKey(
        "med_patients.Patient", on_delete=models.PROTECT, related_name="med_scheduling_appointments"
    )
    appointment_type = models.ForeignKey(AppointmentType, on_delete=models.PROTECT, related_name="+")
    professional = models.ForeignKey(Professional, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    is_fit_in = models.BooleanField(default=False)
    billing_code = models.CharField(max_length=40, blank=True)
    payment_kind = models.CharField(max_length=12, choices=PaymentKind.choices, default=PaymentKind.PRIVATE)
    notes = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=12, choices=CancelReason.choices, blank=True)
    cancel_note = models.CharField(max_length=200, blank=True)
    rescheduled_from = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    immutable_fields = ("schedule_id", "code", "patient_id", "rescheduled_from_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization", "code"), name="med_scheduling_appointment_code", violation_error_code="unique"
            ),
            models.CheckConstraint(
                condition=Q(starts_at__lt=models.F("ends_at")), name="med_scheduling_appointment_window"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=("scheduled", "confirmed", "arrived", "in_progress", "completed", "no_show", "cancelled")
                ),
                name="med_scheduling_appointment_status",
            ),
            models.CheckConstraint(
                condition=Q(payment_kind__in=("private", "insurance", "courtesy")),
                name="med_scheduling_appointment_payment_kind",
            ),
        ]
        indexes = [
            models.Index(fields=("schedule", "starts_at"), name="med_sched_appt_schedule_start"),
            models.Index(fields=("patient", "starts_at"), name="med_sched_appt_patient_start"),
            models.Index(fields=("organization", "status", "starts_at"), name="med_sched_appt_status_start"),
        ]
        ordering = ("starts_at", "sysid")

    def __str__(self) -> str:
        return self.code


class WaitlistEntry(OrganizationRecord):
    """A patient waiting for a slot; the reception books from here, nobody is booked automatically."""

    class Period(models.TextChoices):
        ANY = "any", gettext_lazy("Qualquer horário")
        MORNING = "morning", gettext_lazy("Manhã")
        AFTERNOON = "afternoon", gettext_lazy("Tarde")
        EVENING = "evening", gettext_lazy("Noite")

    class Priority(models.TextChoices):
        NORMAL = "normal", gettext_lazy("Normal")
        HIGH = "high", gettext_lazy("Alta")

    class Status(models.TextChoices):
        WAITING = "waiting", gettext_lazy("Aguardando")
        BOOKED = "booked", gettext_lazy("Agendado")
        CANCELLED = "cancelled", gettext_lazy("Cancelado")
        EXPIRED = "expired", gettext_lazy("Expirado")

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey(
        "med_patients.Patient", on_delete=models.PROTECT, related_name="med_scheduling_waitlist"
    )
    appointment_type = models.ForeignKey(
        AppointmentType, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    preferred_period = models.CharField(max_length=10, choices=Period.choices, default=Period.ANY)
    earliest_date = models.DateField()
    latest_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    note = models.CharField(max_length=200, blank=True)
    booked_appointment = models.ForeignKey(
        Appointment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    immutable_fields = ("practice_id", "patient_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(latest_date__isnull=True) | Q(latest_date__gte=models.F("earliest_date")),
                name="med_scheduling_waitlist_dates",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("waiting", "booked", "cancelled", "expired")),
                name="med_scheduling_waitlist_status",
            ),
        ]
        ordering = ("created_at", "sysid")
