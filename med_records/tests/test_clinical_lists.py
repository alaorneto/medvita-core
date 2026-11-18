"""Allergies, medications in use and the chart summary."""

from datetime import date

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.service_api.audit import AuditService

from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare, save, start


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def chart(ready):
    return open_chart(ready, new_patient(ready))


def service():
    return RecordsService()


def test_allergies_order_and_status(ready, chart):
    with ready.as_user(ready.a.doctor) as doctor:
        mild = service().add_allergy(
            actor=doctor, chart_id=chart.sysid, substance="Dipirona", severity="mild", idempotency_key="a"
        )
        severe = service().add_allergy(
            actor=doctor,
            chart_id=chart.sysid,
            substance="Penicilina",
            category="drug",
            reaction="anafilaxia",
            severity="severe",
            noted_on=date(2020, 1, 1),
            idempotency_key="b",
        )
        assert (
            service().add_allergy(actor=doctor, chart_id=chart.sysid, substance="Dipirona", idempotency_key="a").sysid
            == mild.sysid
        )
        assert [item.substance for item in service().allergies(actor=doctor, chart_id=chart.sysid)] == [
            "Penicilina",
            "Dipirona",
        ]
        resolved = service().update_allergy(
            actor=doctor, allergy_id=mild.sysid, changes=(("status", "resolved"),), expected_revision=mild.revision
        )
        with pytest.raises(Conflict):
            service().update_allergy(
                actor=doctor, allergy_id=mild.sysid, changes=(("status", "active"),), expected_revision=mild.revision
            )
        for changes in ((("status", "gone"),), (("chart", chart.sysid),), (("substance", ""),)):
            with pytest.raises(InvalidInput):
                service().update_allergy(
                    actor=doctor, allergy_id=mild.sysid, changes=changes, expected_revision=resolved.revision
                )
        summary = service().chart_summary(actor=doctor, chart_id=chart.sysid)
        assert [item.sysid for item in summary.allergies] == [severe.sysid]
    with ready.as_user(ready.a.admin) as admin:
        entries = AuditService().history(actor=admin, table_key="med_records.allergy", record_id=mild.sysid).items
    assert [entry.operation for entry in entries][0] in {"update", "UPDATE"}
    assert "Dipirona" not in repr(entries)


def test_medications_and_summary(ready, chart):
    draft = save(ready, start(ready, chart), "med_records.free_text", text="x")
    with ready.as_user(ready.a.doctor) as doctor:
        used = service().add_medication(
            actor=doctor,
            chart_id=chart.sysid,
            name="Losartana",
            dose="50 mg",
            frequency="1x ao dia",
            started_on=date(2025, 1, 1),
            idempotency_key="m",
        )
        old = service().add_medication(actor=doctor, chart_id=chart.sysid, name="Amoxicilina", idempotency_key="n")
        service().update_medication(
            actor=doctor,
            medication_id=old.sysid,
            changes=(("status", "ended"), ("ended_on", date(2025, 2, 1))),
            expected_revision=old.revision,
        )
        with pytest.raises(InvalidInput):
            service().update_medication(
                actor=doctor,
                medication_id=used.sysid,
                changes=(("ended_on", date(2024, 1, 1)),),
                expected_revision=used.revision,
            )
        assert [item.name for item in service().medications(actor=doctor, chart_id=chart.sysid)] == [
            "Losartana",
            "Amoxicilina",
        ]
        summary = service().chart_summary(actor=doctor, chart_id=chart.sysid)
    assert [item.name for item in summary.medications] == ["Losartana"]
    assert [item.sysid for item in summary.latest] == [draft.header.sysid]


def test_reception_and_other_organization(ready, chart):
    with ready.as_user(ready.a.doctor) as doctor:
        row = service().add_allergy(actor=doctor, chart_id=chart.sysid, substance="Látex", idempotency_key="l")
    with ready.as_user(ready.a.reception) as actor:
        for call in (
            lambda: service().allergies(actor=actor, chart_id=chart.sysid),
            lambda: service().chart_summary(actor=actor, chart_id=chart.sysid),
        ):
            with pytest.raises(NotFound):
                call()
    with ready.as_user(ready.a.admin) as admin:
        assert [item.sysid for item in service().allergies(actor=admin, chart_id=chart.sysid)] == [row.sysid]
    with ready.as_user(ready.b.doctor, ready.org_b) as outsider, pytest.raises(NotFound):
        service().update_allergy(
            actor=outsider, allergy_id=row.sysid, changes=(("status", "refuted"),), expected_revision=row.revision
        )


def test_reader_only_cannot_write(ready, chart):
    from skeleton.service_api.access import AccessService

    with ready.as_user(ready.a.admin) as admin:
        (archive,) = service().archives(actor=admin)
        AccessService().grant_record_access(
            actor=admin,
            table_key="med_records.archive",
            record_id=archive.sysid,
            action="read",
            group_id=ready.a.groups["finance"],
        )
    with ready.as_user(ready.a.finance) as reader:
        assert service().allergies(actor=reader, chart_id=chart.sysid) == ()
        with pytest.raises(Forbidden):
            service().add_allergy(actor=reader, chart_id=chart.sysid, substance="X", idempotency_key="x")
