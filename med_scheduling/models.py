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
    """A kind of appointment: duration, color and the opaque billing code finance resolves."""

    practice = models.ForeignKey(Practice, on_delete=models.PROTECT, related_name="+")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    duration_minutes = models.PositiveSmallIntegerField(default=30)
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
        ]
        ordering = ("name", "sysid")
