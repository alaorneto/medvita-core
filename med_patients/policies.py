"""Authorization shortcuts of the patients app: everything derives from the patient registry.

- Reading a patient (and its guardians, coverages and consents) needs ``read`` on the registry.
- Writing them needs ``update`` on the registry.
- Privacy operations (data report, restriction, anonymization) need ``manage_access`` on it.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet

from skeleton.access.policies import authorized_queryset

from .models import Patient, PatientRegistry

REGISTRY_TABLE = "med_patients.patientregistry"
PATIENT_TABLE = "med_patients.patient"


def readable_registries(user: Any) -> QuerySet[PatientRegistry]:
    return authorized_queryset(PatientRegistry, user=user, action="read")


def writable_registries(user: Any) -> QuerySet[PatientRegistry]:
    return authorized_queryset(PatientRegistry, user=user, action="update")


def readable_patients(user: Any) -> QuerySet[Patient]:
    return authorized_queryset(Patient, user=user, action="read")


def writable_patients(user: Any) -> QuerySet[Patient]:
    return authorized_queryset(Patient, user=user, action="update")


def ids_allowed(queryset_factory: Any, user: Any) -> set[Any]:
    """Primary keys the actor reaches through ``queryset_factory``; empty when the table is refused."""
    try:
        return set(queryset_factory(user).values_list("pk", flat=True))
    except PermissionDenied:
        return set()
