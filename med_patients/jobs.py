"""Jobs of the CSV import: validate a mapped batch, then apply it 200 rows per job.

Both run as the actor who started the import (``run_as="actor"``): the worker re-enters the
organization as that person, so an actor who lost write access to the registry makes the batch
fail instead of writing. A job is one transaction; the apply job chains the next one, so each
chunk of 200 rows commits on its own and a failure only repeats its own chunk. Every patient is
created with a key derived from the batch and the row, so running a chunk again never duplicates.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils import timezone

APP_LABEL = "med_patients"
VALIDATE_JOB = "med_patients.import_validate"
APPLY_JOB = "med_patients.import_apply"
CHUNK = 200
MAX_REPORT = 1000


def _batch(actor: Any, batch_id: UUID) -> Any:
    from skeleton.access.policies import authorized_queryset

    from .models import ImportBatch

    return authorized_queryset(ImportBatch, user=actor, action="read").select_for_update().filter(pk=batch_id).first()


def _can_write(actor: Any, batch: Any) -> bool:
    from .policies import writable_registries

    return writable_registries(actor).filter(pk=batch.registry_id).exists()


def _fail(batch: Any, code: str) -> None:
    batch.status = batch.Status.FAILED
    batch.error_code = code
    batch.content = ""
    batch.finished_at = timezone.now()
    batch.save(update_fields={"status", "error_code", "content", "finished_at"})


def _live_cpfs(actor: Any) -> set[str]:
    from .policies import readable_patients

    return set(readable_patients(actor).exclude(cpf="").values_list("cpf", flat=True))


def enqueue(actor: Any, job_type: str, batch: Any, *, step: int = 0) -> None:
    from skeleton.service_api.jobs import JobService

    JobService().enqueue(
        actor=actor,
        job_type=job_type,
        payload=(("batch_id", batch.pk),),
        idempotency_key=f"{job_type}:{batch.pk}:{step}",
    )


def validate_batch(*, actor: Any, batch_id: UUID) -> None:
    from skeleton.service_api import InvalidInput

    from .importer import data_rows, error_code, mapped_values
    from .services import clean_patient_values

    batch = _batch(actor, batch_id)
    if batch is None or batch.status != batch.Status.VALIDATING:
        return
    if not _can_write(actor, batch):
        _fail(batch, "forbidden")
        return
    mapping = dict(batch.mapping)
    existing = _live_cpfs(actor)
    seen: set[str] = set()
    report: list[list[Any]] = []
    valid = skipped = errors = 0
    for number, cells in data_rows(batch.content, batch.delimiter):
        try:
            clean = clean_patient_values(mapped_values(cells, mapping), partial=False)
        except InvalidInput as error:
            errors += 1
            report.append([number, error_code(dict(error.errors))])
            continue
        cpf = clean.get("cpf") or ""
        if cpf and (cpf in existing or cpf in seen):
            skipped += 1
            report.append([number, "duplicate_cpf"])
            continue
        if cpf:
            seen.add(cpf)
        valid += 1
    batch.status = batch.Status.VALIDATED
    batch.valid_rows, batch.skipped_rows, batch.error_rows = valid, skipped, errors
    batch.report = report[:MAX_REPORT]
    batch.save(update_fields={"status", "valid_rows", "skipped_rows", "error_rows", "report"})


def apply_batch(*, actor: Any, batch_id: UUID) -> None:
    from skeleton.service_api import Conflict, InvalidInput

    from .importer import data_rows, mapped_values
    from .service_api import PatientInput, PatientService
    from .services import clean_patient_values

    batch = _batch(actor, batch_id)
    if batch is None or batch.status != batch.Status.IMPORTING:
        return
    if not _can_write(actor, batch):
        _fail(batch, "forbidden")
        return
    rows = list(data_rows(batch.content, batch.delimiter))
    start = batch.applied_rows
    mapping = dict(batch.mapping)
    existing = _live_cpfs(actor)
    service = PatientService()
    created = skipped = errors = 0
    for number, cells in rows[start : start + CHUNK]:
        try:
            clean = clean_patient_values(mapped_values(cells, mapping), partial=False)
        except InvalidInput:
            errors += 1
            continue
        if clean.get("cpf") and clean["cpf"] in existing:
            skipped += 1
            continue
        try:
            info = service.create(
                actor=actor,
                data=PatientInput(**clean),
                registry_id=batch.registry_id,
                idempotency_key=f"import:{batch.pk}:{number}",
            )
        except Conflict:
            skipped += 1  # Another patient took the CPF meanwhile.
            continue
        if info.cpf:
            existing.add(info.cpf)
        created += 1
    batch.applied_rows = min(start + CHUNK, len(rows))
    batch.created_rows += created
    batch.skipped_rows += skipped
    batch.error_rows += errors
    fields = {"applied_rows", "created_rows", "skipped_rows", "error_rows"}
    if batch.applied_rows >= len(rows):
        batch.status = batch.Status.COMPLETED
        batch.content = ""
        batch.finished_at = timezone.now()
        fields |= {"status", "content", "finished_at"}
    batch.save(update_fields=fields)
    if batch.status == batch.Status.IMPORTING:
        enqueue(actor, APPLY_JOB, batch, step=batch.applied_rows)
