"""Tables of the records app (docs/spec.md, "Modelo de dados").

One container decides access: ``Archive`` (a clinical archive, of the whole clinic or of one
professional). Every other table is derived from it (``TableSpec.access_parent``), directly or
through the patient's chart. Clinical content is in ``sensitive_fields``.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from skeleton.common.models import OrganizationRecord, SealableMixin, SecuredRecord


class Archive(SecuredRecord):
    """A clinical archive: the unit of confidentiality (who reads it reads its charts)."""

    class Kind(models.TextChoices):
        SHARED = "shared", gettext_lazy("Da clínica")
        PERSONAL = "personal", gettext_lazy("De um profissional")

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SHARED)
    is_default = models.BooleanField(default=False)
    immutable_fields = ("kind",)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_records_one_default_archive",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class PatientChart(OrganizationRecord):
    """The chart of one patient in one archive."""

    archive = models.ForeignKey(Archive, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="med_records_charts")
    opened_at = models.DateTimeField()
    last_entry_at = models.DateTimeField(null=True, blank=True)
    immutable_fields = ("archive_id", "patient_id", "opened_at")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("archive", "patient"),
                condition=Q(deleted_at__isnull=True),
                name="med_records_one_chart_per_archive",
                violation_error_code="unique",
            ),
        ]
        indexes = [models.Index(fields=("organization", "patient"), name="med_records_chart_patient")]
        ordering = ("opened_at", "sysid")


class Encounter(SealableMixin, OrganizationRecord):
    """One encounter of the chart: a draft only its author changes, sealed when signed.

    A signed encounter never changes; a correction is an addendum (``kind="addendum"``) pointing
    to the original with ``amends``.
    """

    class Kind(models.TextChoices):
        CONSULTATION = "consultation", gettext_lazy("Consulta")
        RETURN = "return", gettext_lazy("Retorno")
        PROCEDURE = "procedure", gettext_lazy("Procedimento")
        REMOTE_CONTACT = "remote_contact", gettext_lazy("Contato a distância")
        NOTE = "note", gettext_lazy("Anotação")
        ADDENDUM = "addendum", gettext_lazy("Adendo")

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CONSULTATION)
    occurred_at = models.DateTimeField()
    author = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    author_name = models.CharField(max_length=200, blank=True)
    author_council = models.CharField(max_length=60, blank=True)
    appointment = models.ForeignKey(
        "med_scheduling.Appointment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    amends = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # The references are immutable from creation (immutable_fields); the seal digest covers them
    # through ``seal_extra`` and the seal freezes the columns a draft may still change.
    seal_fields = ("code", "kind", "occurred_at", "author_name", "author_council")
    immutable_fields = ("chart_id", "patient_id", "author_id", "appointment_id", "amends_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(fields=("organization", "code"), name="med_records_encounter_code"),
            models.CheckConstraint(
                condition=Q(kind="addendum", amends__isnull=False) | (~Q(kind="addendum") & Q(amends__isnull=True)),
                name="med_records_addendum_amends",
            ),
        ]
        indexes = [models.Index(fields=("chart", "occurred_at"), name="med_records_encounter_chart")]
        ordering = ("-occurred_at", "sysid")


class EncounterSection(OrganizationRecord):
    """A structured section of an encounter; frozen with the encounter's seal."""

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="+")
    section_type = models.CharField(max_length=80)
    type_version = models.PositiveSmallIntegerField(default=1)
    position = models.PositiveSmallIntegerField(default=0)
    data = models.JSONField(default=dict, blank=True)
    text = models.TextField(blank=True)
    seal_parent = "encounter"
    immutable_fields = ("encounter_id", "section_type")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("encounter", "section_type", "position"),
                condition=Q(deleted_at__isnull=True),
                name="med_records_one_section_per_slot",
                violation_error_code="unique",
            ),
        ]
        ordering = ("position", "section_type", "sysid")
