"""Tables of the patients app (docs/spec.md, "Modelo de dados").

``PatientRegistry`` is the only container (an exposed ``SecuredRecord``); every other table is
derived from it (``TableSpec.access_parent``): reading a child needs ``read`` on the registry,
writing it needs ``update`` on the registry.

The rows that belong to a patient (guardians, coverages, consents) point to it with a hidden
reverse relation (``related_name="+"``): the core does not count them as live references, so
deleting a patient hides them with it (derived access) and restoring the patient brings them back.
Rows of other apps (appointments, charts, charges) keep protecting a live patient.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from skeleton.common.models import OrganizationRecord, SecuredRecord


class PatientRegistry(SecuredRecord):
    """The patient registry of the clinic: whoever writes it writes its patients."""

    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization", "name"),
                condition=Q(deleted_at__isnull=True),
                name="med_patients_registry_live_name",
                violation_error_code="unique",
            ),
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_patients_one_default_registry",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class Patient(OrganizationRecord):
    """A patient of the organization: a record, never a user."""

    class Sex(models.TextChoices):
        FEMALE = "female", gettext_lazy("Feminino")
        MALE = "male", gettext_lazy("Masculino")
        INTERSEX = "intersex", gettext_lazy("Intersexo")
        UNKNOWN = "unknown", gettext_lazy("Não informado")

    class Status(models.TextChoices):
        ACTIVE = "active", gettext_lazy("Ativo")
        INACTIVE = "inactive", gettext_lazy("Inativo")
        DECEASED = "deceased", gettext_lazy("Falecido")

    class ContactPreference(models.TextChoices):
        PHONE = "phone", gettext_lazy("Telefone")
        WHATSAPP = "whatsapp", gettext_lazy("WhatsApp")
        EMAIL = "email", gettext_lazy("Email")
        NONE = "none", gettext_lazy("Nenhum")

    registry = models.ForeignKey(PatientRegistry, on_delete=models.PROTECT, related_name="patients")
    code = models.CharField(max_length=20)
    full_name = models.CharField(max_length=200)
    social_name = models.CharField(max_length=200, blank=True)
    search_name = models.CharField(max_length=420, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=12, choices=Sex.choices, default=Sex.UNKNOWN)
    cpf = models.CharField(max_length=11, blank=True)
    national_health_card = models.CharField(max_length=15, blank=True)
    identity_document = models.CharField(max_length=30, blank=True)
    mother_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    phone_secondary = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    contact_preference = models.CharField(
        max_length=12, choices=ContactPreference.choices, default=ContactPreference.PHONE
    )
    postal_code = models.CharField(max_length=8, blank=True)
    street = models.CharField(max_length=120, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    deceased_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    processing_restricted = models.BooleanField(default=False)
    anonymized_at = models.DateTimeField(null=True, blank=True)
    immutable_fields = ("registry_id", "code")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization", "code"), name="med_patients_patient_code", violation_error_code="unique"
            ),
            models.UniqueConstraint(
                fields=("organization", "cpf"),
                condition=Q(deleted_at__isnull=True) & ~Q(cpf=""),
                name="med_patients_patient_live_cpf",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(sex__in=("female", "male", "intersex", "unknown")), name="med_patients_patient_sex"
            ),
            models.CheckConstraint(
                condition=Q(status__in=("active", "inactive", "deceased")), name="med_patients_patient_status"
            ),
            models.CheckConstraint(
                condition=~Q(status="deceased") | Q(deceased_on__isnull=False),
                name="med_patients_patient_deceased_on",
            ),
            models.CheckConstraint(condition=Q(cpf__regex=r"^([0-9]{11})?$"), name="med_patients_patient_cpf"),
        ]
        indexes = [
            models.Index(fields=("organization", "search_name"), name="med_patients_patient_search"),
            models.Index(fields=("organization", "birth_date"), name="med_patients_patient_birth"),
            models.Index(fields=("organization", "phone"), name="med_patients_patient_phone"),
        ]
        ordering = ("search_name", "sysid")

    def __str__(self) -> str:
        return self.code

    @property
    def display_name(self) -> str:
        return self.social_name or self.full_name
