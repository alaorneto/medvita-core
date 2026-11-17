"""CSV import end to end: upload, map, validate and apply by jobs, as the actor who started it."""

import io
import json
from itertools import count

import pytest
from django.db import transaction
from django.test import override_settings

from skeleton.service_api import Conflict, InvalidInput, NotFound
from skeleton.testing.jobs import run_pending_jobs

from .. import jobs
from ..service_api import PatientService
from .helpers import new_patient, setup_registry


def valid_cpfs():
    """CPFs with valid check digits, generated from a counter."""
    for base in count(100_000_000):
        digits = [int(char) for char in f"{base:09d}"]
        for size in (9, 10):
            total = sum(number * (size + 1 - index) for index, number in enumerate(digits[:size]))
            digits.append((total * 10) % 11 % 10)
        if len(set(digits)) > 1:
            yield "".join(map(str, digits))


@pytest.fixture
def ready(clinic, tmp_path):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    from django.conf import settings

    storage = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(tmp_path / "files"), "base_url": None},
    }
    with override_settings(STORAGES={**settings.STORAGES, "skeleton_files": storage}):
        yield clinic


def service():
    return PatientService()


def csv_bytes(rows):
    lines = ["Nome;CPF;Nascimento"] + [";".join(row) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def start_and_map(clinic, raw, key="imp"):
    with clinic.as_user(clinic.a.reception) as actor:
        batch = service().start_import(actor=actor, stream=io.BytesIO(raw), idempotency_key=key)
        mapping = (("Nome", "full_name"), ("CPF", "cpf"), ("Nascimento", "birth_date"))
        return service().map_import(
            actor=actor, batch_id=batch.sysid, mapping=mapping, expected_revision=batch.revision
        )


def status(clinic, batch_id, user=None):
    with clinic.as_user(user or clinic.a.reception) as actor:
        return service().import_status(actor=actor, batch_id=batch_id)


def test_import_500_rows_with_invalid_and_repeated_cpfs(ready):
    generator = valid_cpfs()
    already = [next(generator) for _ in range(5)]
    for index, cpf in enumerate(already):
        new_patient(ready, full_name=f"Já cadastrado {index}", cpf=cpf)
    rows = []
    for index in range(500):
        if index < 10:
            rows.append((f"Inválido {index}", "11111111111", "1990-01-01"))
        elif index < 15:
            rows.append((f"Repetido {index}", already[index - 10], ""))
        else:
            rows.append((f"Paciente {index}", next(generator), "1985-05-05"))
    batch = start_and_map(ready, csv_bytes(rows))
    assert batch.status == "validating" and batch.total_rows == 500
    run_pending_jobs()
    checked = status(ready, batch.sysid)
    assert (checked.status, checked.valid_rows, checked.skipped_rows, checked.error_rows) == ("validated", 485, 5, 10)
    assert {code for _row, code in checked.report} == {"invalid_cpf", "duplicate_cpf"}
    with ready.as_user(ready.a.reception) as actor:
        service().apply_import(actor=actor, batch_id=batch.sysid, expected_revision=checked.revision)
    run_pending_jobs()
    done = status(ready, batch.sysid)
    assert (done.status, done.created_rows, done.skipped_rows, done.error_rows) == ("completed", 485, 5, 10)
    assert done.applied_rows == 500 and done.finished_at is not None
    with ready.as_user(ready.a.reception) as actor:
        page = service().search(actor=actor, query="paciente", page_size=100)
        assert len(page.items) == 100
    serialized = json.dumps([list(item) for item in done.report])
    assert "Inválido" not in serialized and "11111111111" not in serialized


def test_running_a_chunk_again_does_not_duplicate(ready):
    generator = valid_cpfs()
    rows = [(f"Pessoa {index}", next(generator), "") for index in range(250)]
    batch = start_and_map(ready, csv_bytes(rows))
    run_pending_jobs()
    with ready.as_user(ready.a.reception) as actor:
        checked = service().import_status(actor=actor, batch_id=batch.sysid)
        service().apply_import(actor=actor, batch_id=batch.sysid, expected_revision=checked.revision)
    run_pending_jobs(limit=1)  # The first chunk of 200 committed; the next job is queued.
    assert status(ready, batch.sysid).applied_rows == 200
    with ready.as_user(ready.a.reception) as actor, transaction.atomic():
        # The first chunk runs again, as a retry after a lost lease would: nothing is duplicated.
        from ..models import ImportBatch

        ImportBatch.objects.filter(pk=batch.sysid).update(applied_rows=0)
        jobs.apply_batch(actor=actor, batch_id=batch.sysid)
    run_pending_jobs()
    done = status(ready, batch.sysid)
    assert done.status == "completed"
    with ready.as_user(ready.a.reception) as actor:
        found = service().search(actor=actor, query="pessoa", page_size=100)
        total, cursor = len(found.items), found.next_cursor
        while cursor:
            found = service().search(actor=actor, query="pessoa", page_size=100, cursor=cursor)
            total, cursor = total + len(found.items), found.next_cursor
    assert total == 250


def test_actor_without_write_access_makes_the_batch_fail(ready):
    batch = start_and_map(ready, csv_bytes([("Fulano", "", "")]))
    from skeleton.service_api.access import AccessService

    with ready.as_user(ready.a.admin) as admin:
        registry = service().registries(actor=admin)[0]
        AccessService().revoke_record_access(
            actor=admin,
            table_key="med_patients.patientregistry",
            record_id=registry.sysid,
            action="update",
            group_id=ready.a.groups["reception"],
        )
    run_pending_jobs()
    failed = status(ready, batch.sysid)
    assert (failed.status, failed.error_code) == ("failed", "forbidden")


def test_refused_files_and_isolation(ready, subtests):
    with ready.as_user(ready.a.reception) as actor:
        for name, raw in (("not csv", b"\x00\x00\x00"), ("empty", b"Nome\n")):
            with subtests.test(name), pytest.raises(InvalidInput):
                service().start_import(actor=actor, stream=io.BytesIO(raw), idempotency_key=name)
        assert service().imports(actor=actor) == ()
    batch = start_and_map(ready, csv_bytes([("Ana", "", "")]))
    with subtests.test("organization B"), ready.as_user(ready.b.reception, ready.org_b) as actor:
        with pytest.raises(NotFound):
            service().import_status(actor=actor, batch_id=batch.sysid)
    with subtests.test("mapping needs the full name"), ready.as_user(ready.a.reception) as actor:
        current = service().import_status(actor=actor, batch_id=batch.sysid)
        with pytest.raises(Conflict):
            service().map_import(
                actor=actor, batch_id=batch.sysid, mapping=(("CPF", "cpf"),), expected_revision=current.revision
            )
