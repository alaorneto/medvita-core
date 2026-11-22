"""Waitlist: entries, candidates for a free time, booking from it and the expiry job."""

from datetime import date, timedelta

import pytest

from applications.med_patients.service_api import PatientInput, PatientService
from skeleton.service_api import Conflict, InvalidInput
from skeleton.service_api.jobs import JobService
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.jobs import run_pending_jobs
from skeleton.testing.service_api import acting_as, build_service_scenario

from ..models import Practice, WaitlistEntry
from ..service_api import SchedulingService
from .booking import at, book, prepare
from .helpers import new_patient


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def wait(ready, patient, key, **values):
    values.setdefault("earliest_date", ready.monday - timedelta(days=1))
    with ready.as_user(ready.a.reception) as actor:
        return service().add_to_waitlist(actor=actor, patient_id=patient.sysid, idempotency_key=key, **values)


def test_candidates_order_and_fit(ready):
    other = new_patient(ready, full_name="Outra Pessoa")
    third = new_patient(ready, full_name="Terceira")
    normal = wait(ready, ready.patient, "a", appointment_type_id=ready.kind.sysid)
    urgent = wait(ready, other, "b", appointment_type_id=ready.kind.sysid, priority="high")
    wait(ready, third, "c", preferred_period="afternoon")
    with ready.as_user(ready.a.reception) as actor:
        found = service().waitlist_candidates(
            actor=actor, schedule_id=ready.schedule.sysid, starts_at=at(ready, 9), ends_at=at(ready, 9, 30)
        )
    assert [item.sysid for item in found] == [urgent.sysid, normal.sysid]


def test_the_note_is_sensitive(ready):
    from skeleton.service_api.audit import AuditService

    entry = wait(ready, ready.patient, "noted", note="Prefere depois do trabalho")
    with ready.as_user(ready.a.admin) as admin:
        entries = AuditService().history(actor=admin, table_key="med_scheduling.waitlistentry", record_id=entry.sysid)
    assert "Prefere depois" not in str([change.new for item in entries.items for change in item.changes])


def test_book_from_waitlist(ready):
    entry = wait(ready, ready.patient, "a", appointment_type_id=ready.kind.sysid)
    book(ready, 9, key="taken", patient_id=new_patient(ready, full_name="Ocupante").sysid)
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict):
            service().book_from_waitlist(
                actor=actor,
                entry_id=entry.sysid,
                schedule_id=ready.schedule.sysid,
                starts_at=at(ready, 9),
                expected_revision=entry.revision,
                idempotency_key="busy",
            )
        assert service().waitlist(actor=actor).items[0].status == "waiting"
        appointment = service().book_from_waitlist(
            actor=actor,
            entry_id=entry.sysid,
            schedule_id=ready.schedule.sysid,
            starts_at=at(ready, 10),
            expected_revision=entry.revision,
            idempotency_key="free",
        )
        booked = service().waitlist(actor=actor, status="booked").items
    assert [(item.sysid, item.booked_appointment_id) for item in booked] == [(entry.sysid, appointment.sysid)]


def test_expiry_job_is_idempotent(ready):
    old = wait(ready, ready.patient, "old", earliest_date=date(2025, 1, 1), latest_date=date(2025, 1, 31))
    fresh = wait(ready, new_patient(ready, full_name="Nova"), "new", latest_date=date.today() + timedelta(days=30))
    for attempt in ("1", "2"):
        with ready.as_user(ready.a.admin) as admin:
            JobService().enqueue(actor=admin, job_type="med_scheduling.expire_waitlist", idempotency_key=attempt)
        run_pending_jobs()
    with ready.as_user(ready.a.reception) as actor:
        assert [item.sysid for item in service().waitlist(actor=actor, status="expired").items] == [old.sysid]
        assert [item.sysid for item in service().waitlist(actor=actor).items] == [fresh.sysid]


def test_waitlist_follows_the_practice(skeleton_db):
    for label in ("med_patients", "skeleton_calendar", "med_scheduling"):
        open_app(label)
    scenario = build_service_scenario(WaitlistEntry, slug="waitlist")
    patients = {}
    for organization, admin in ((scenario.a, scenario.admin_a), (scenario.b, scenario.admin_b)):
        with acting_as(admin, organization) as actor:
            PatientService().setup(actor=actor, name="Pacientes", idempotency_key="p")
            patients[organization.pk] = PatientService().create(actor=actor, data=PatientInput(full_name="Fila")).sysid

    def make_practice(*, organization, owner):
        practice = Practice(organization=organization, owner=owner, visibility="private", name="Consultório")
        practice.save()
        return practice

    def make_entry(practice):
        entry = WaitlistEntry(
            organization=practice.organization,
            practice=practice,
            patient_id=patients[practice.organization_id],
            earliest_date=date(2026, 1, 1),
        )
        entry.save()
        return entry

    assert_derived_access_contract(
        child_model=WaitlistEntry, make_anchor=make_practice, make_child=make_entry, scenario=scenario
    )


def test_book_from_waitlist_takes_the_payment_of_the_kind_and_the_duration_given(ready):
    with ready.as_user(ready.a.admin) as admin:
        insured = service().add_appointment_type(
            actor=admin,
            code="unimed",
            name="Unimed",
            duration_minutes=20,
            payment_kind="insurance",
            idempotency_key="unimed",
        )
    other = new_patient(ready, full_name="Outra Pessoa")
    first = wait(ready, ready.patient, "a", appointment_type_id=insured.sysid)
    second = wait(ready, other, "b", appointment_type_id=insured.sysid)

    def book_entry(entry, hour, **extra):
        with ready.as_user(ready.a.reception) as actor:
            return service().book_from_waitlist(
                actor=actor,
                entry_id=entry.sysid,
                schedule_id=ready.schedule.sysid,
                starts_at=at(ready, hour),
                expected_revision=entry.revision,
                idempotency_key=f"entry-{hour}",
                **extra,
            )

    plain = book_entry(first, 9)
    assert (plain.payment_kind, plain.ends_at) == ("insurance", at(ready, 9, 20))
    with pytest.raises(InvalidInput):
        book_entry(second, 10, duration_minutes=481)
    longer = book_entry(second, 10, duration_minutes=45)
    assert (longer.payment_kind, longer.ends_at) == ("insurance", at(ready, 10, 45))
