"""Tables of the records app (docs/spec.md, "Modelo de dados").

One container decides access: ``Archive`` (a clinical archive, of the whole clinic or of one
professional). Every other table is derived from it (``TableSpec.access_parent``), directly or
through the patient's chart. Clinical content is in ``sensitive_fields``.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from skeleton.common.models import OrganizationRecord, SecuredRecord


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
