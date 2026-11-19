"""Tables of the reference app: a board (container) and its notes about patients (derived)."""

from __future__ import annotations

from django.db import models

from skeleton.common.models import OrganizationRecord, SecuredRecord


class ExampleBoard(SecuredRecord):
    name = models.CharField(max_length=120)

    class Meta(SecuredRecord.Meta):
        ordering = ("name", "sysid")


class ExampleNote(OrganizationRecord):
    """A note about a patient, written by a person or by a consumer of another app's event."""

    board = models.ForeignKey(ExampleBoard, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="+")
    source = models.CharField(max_length=80, blank=True)
    source_key = models.CharField(max_length=80, blank=True)
    text = models.CharField(max_length=300)
    keep = models.BooleanField(default=False)
    immutable_fields = ("board_id", "patient_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization", "source", "source_key"),
                condition=~models.Q(source_key=""),
                name="med_example_one_note_per_event",
            ),
        ]
        ordering = ("created_at", "sysid")
