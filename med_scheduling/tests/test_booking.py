"""Booking, fit-in, rescheduling and cancelling, with the calendar projection and the events."""

from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.events import capture_events
from skeleton.testing.service_api import assert_cas_conflict

from ..service_api import SchedulingService
from .booking import at, book, prepare

PAYLOAD = {"code", "schedule", "patient", "appointment_type", "billing_code", "starts_at", "ends_at", "status"}


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def event_of(ready, appointment, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return CalendarService().managed_event(
            actor=actor, source_app="med_scheduling", source_key=str(appointment.sysid)
        )


def test_book_projects_and_publishes_without_the_patient(ready):
    with capture_events() as events:
        appointment = book(ready, 9)
    assert appointment.code == "A0000001" and appointment.status == "scheduled" and appointment.billing_code == "C1"
    assert [event.event_type for event in events] == ["med_scheduling.appointment_booked"]
    payload = dict(events[0].data)
    assert set(payload) == PAYLOAD and payload["patient"] == str(ready.patient.sysid)
    projected = event_of(ready, appointment)
    assert projected.title == "Consulta · A0000001"
    assert "Maria" not in projected.title and "Secreta" not in projected.title
    assert projected.starts_at == at(ready, 9)


def test_same_slot_twice_and_the_lock(ready):
    book(ready, 9)
    with pytest.raises(Conflict) as error:
        book(ready, 9, key="second")
    assert error.value.code == "slot_unavailable"
    with CaptureQueriesContext(connection) as queries, ready.as_user(ready.a.reception) as actor:
        service().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            starts_at=at(ready, 10),
            idempotency_key="locked",
        )
    assert any(
        "FOR UPDATE" in query["sql"] and "med_scheduling_schedule" in query["sql"] for query in queries.captured_queries
    )


def test_grid_blocks_and_fit_in(ready, subtests):
    with subtests.test("outside the grid"), pytest.raises(Conflict):
        book(ready, 13)
    first = book(ready, 9)
    with subtests.test("fit-in overlaps"):
        squeezed = book(ready, 9, key="fit", fit_in=True)
        assert squeezed.is_fit_in and squeezed.starts_at == first.starts_at
    with ready.as_user(ready.a.reception) as actor:
        service().add_block(
            actor=actor, schedule_id=ready.schedule.sysid, starts_at=at(ready, 11), ends_at=at(ready, 12)
        )
    with subtests.test("never over a block"), pytest.raises(Conflict):
        book(ready, 11, key="blocked", fit_in=True)


def test_idempotent_booking(ready):
    with capture_events() as events:
        one = book(ready, 9, key="same")
        two = book(ready, 9, key="same")
    assert one.sysid == two.sysid and len(events) == 1
    with ready.as_user(ready.a.reception) as actor:
        assert len(service().appointments(actor=actor, schedule_id=ready.schedule.sysid).items) == 1


def test_reschedule_and_cancel(ready):
    appointment = book(ready, 9)
    with ready.as_user(ready.a.reception) as actor, capture_events() as events:
        moved = service().reschedule(
            actor=actor,
            appointment_id=appointment.sysid,
            starts_at=at(ready, 10),
            expected_revision=appointment.revision,
        )
        assert (moved.status, moved.starts_at, moved.code) == ("scheduled", at(ready, 10), appointment.code)
        assert [event.event_type for event in events] == ["med_scheduling.appointment_rescheduled"]
    assert event_of(ready, appointment).starts_at == at(ready, 10)
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(InvalidInput):
            service().cancel(
                actor=actor, appointment_id=appointment.sysid, reason="boredom", expected_revision=moved.revision
            )
        cancelled = service().cancel(
            actor=actor, appointment_id=appointment.sysid, reason="patient", expected_revision=moved.revision
        )
        assert cancelled.status == "cancelled"
        with pytest.raises(Conflict):
            service().cancel(
                actor=actor, appointment_id=appointment.sysid, reason="patient", expected_revision=cancelled.revision
            )
    assert event_of(ready, appointment) is None
    assert book(ready, 10, key="after-cancel").starts_at == at(ready, 10)


def test_reschedule_to_another_schedule(ready):
    with ready.as_user(ready.a.admin) as admin:
        other = service().create_schedule(
            actor=admin,
            name="Agenda 2",
            professional_id=ready.doctor.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            idempotency_key="two",
        )
        from ..service_api import AvailabilityRuleInput

        service().set_availability(
            actor=admin,
            schedule_id=other.sysid,
            rules=(AvailabilityRuleInput(0, 14 * 60, 18 * 60, ready.monday),),
            expected_revision=other.revision,
        )
    appointment = book(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        moved = service().reschedule(
            actor=actor,
            appointment_id=appointment.sysid,
            starts_at=at(ready, 15),
            schedule_id=other.sysid,
            expected_revision=appointment.revision,
        )
        old = service().appointment(actor=actor, appointment_id=appointment.sysid)
    assert moved.schedule_id == other.sysid and moved.rescheduled_from_id == appointment.sysid
    assert (old.appointment.status, old.cancel_reason) == ("cancelled", "rescheduled")


def test_cas_on_appointments(ready):
    appointment = book(ready, 9)

    def confirm():
        with ready.as_user(ready.a.reception) as actor:
            return service().cancel(
                actor=actor, appointment_id=appointment.sysid, reason="patient", expected_revision=appointment.revision
            )

    def move():
        with ready.as_user(ready.a.reception) as actor:
            return service().reschedule(
                actor=actor,
                appointment_id=appointment.sysid,
                starts_at=at(ready, 11),
                expected_revision=appointment.revision,
            )

    assert assert_cas_conflict(confirm, move).status == "cancelled"


def test_authorization_isolation_and_notes(ready, subtests):
    appointment = book(ready, 9, notes="Dor de cabeça há três dias")
    with subtests.test("finance does not see the schedule"), ready.as_user(ready.a.finance) as actor:
        with pytest.raises(NotFound):
            service().appointment(actor=actor, appointment_id=appointment.sysid)
        assert service().appointments(actor=actor, patient_id=ready.patient.sysid).items == ()
    with subtests.test("organization B"), ready.as_user(ready.b.reception, ready.org_b) as actor:
        with pytest.raises(NotFound):
            service().appointment(actor=actor, appointment_id=appointment.sysid)
    with subtests.test("the professional reads the own schedule"), ready.as_user(ready.a.doctor) as actor:
        detail = service().appointment(actor=actor, appointment_id=appointment.sysid)
        assert detail.notes == "Dor de cabeça há três dias"
    with subtests.test("a reader does not book"), ready.as_user(ready.a.finance) as actor:
        with pytest.raises((Forbidden, NotFound)):
            service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=at(ready, 10),
                idempotency_key="x",
            )
    with subtests.test("audit redacts the notes"), ready.as_user(ready.a.admin) as admin:
        from skeleton.service_api.audit import AuditService

        entries = AuditService().history(
            actor=admin, table_key="med_scheduling.appointment", record_id=appointment.sysid
        )
        assert "Dor de cabeça" not in str([change.new for entry in entries.items for change in entry.changes])


def test_rollback_leaves_nothing(ready):
    with capture_events(), pytest.raises(RuntimeError), transaction.atomic():
        appointment = book(ready, 9)
        raise RuntimeError("rollback")
    assert event_of(ready, appointment) is None
    with ready.as_user(ready.a.reception) as actor:
        assert service().appointments(actor=actor).items == ()


def test_every_free_slot_can_be_booked(ready):
    book(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        free = service().available_slots(
            actor=actor, schedule_id=ready.schedule.sysid, start_date=ready.monday, end_date=ready.monday
        )
    assert at(ready, 9) not in {slot.starts_at for slot in free} and len(free) == 7
    for index, slot in enumerate(free):
        with ready.as_user(ready.a.reception) as actor:
            service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=slot.starts_at,
                idempotency_key=f"slot-{index}",
            )


def test_day_costs_the_same_queries_whatever_the_appointments(ready):
    def count_day():
        with CaptureQueriesContext(connection) as queries, ready.as_user(ready.a.reception) as actor:
            (agenda,) = service().day(actor=actor, date=ready.monday)
        return len(queries.captured_queries), agenda

    book(ready, 8)
    few, agenda = count_day()
    assert len(agenda.appointments) == 1
    for minute in range(30, 240, 30):
        start = at(ready, 8) + timedelta(minutes=minute)
        book(ready, start.hour, start.minute, key=f"many-{minute}")
    many, agenda = count_day()
    assert len(agenda.appointments) == 8 and agenda.free == ()
    assert many == few
