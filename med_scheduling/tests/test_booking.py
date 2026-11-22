"""Booking, fit-in, rescheduling and cancelling, with the calendar projection and the events."""

from datetime import date, timedelta

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.events import capture_events
from skeleton.testing.service_api import assert_cas_conflict

from ..service_api import AvailabilityRuleInput, SchedulingService
from .booking import SP, at, book, prepare

PAYLOAD = {
    "code",
    "schedule",
    "patient",
    "appointment_type",
    "billing_code",
    "starts_at",
    "ends_at",
    "status",
    "mode",
}


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
    assert payload["mode"] == "booked" and appointment.mode == "booked" and appointment.duration_minutes == 30
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


def afternoon_schedule(ready, key="two", **access):
    """A second schedule of Dra. Ana, 14:00-18:00 on Mondays; the reception writes unless ``access`` says otherwise."""
    access = access or {"writer_group_ids": (ready.a.groups["reception"],)}
    with ready.as_user(ready.a.admin) as admin:
        other = service().create_schedule(
            actor=admin, name=f"Agenda {key}", professional_id=ready.doctor.sysid, idempotency_key=key, **access
        )
        service().set_availability(
            actor=admin,
            schedule_id=other.sysid,
            rules=(AvailabilityRuleInput(0, 14 * 60, 18 * 60, ready.monday),),
            expected_revision=other.revision,
        )
    return other


def move(ready, appointment, hour, minute=0, **extra):
    with ready.as_user(ready.a.reception) as actor:
        return service().reschedule(
            actor=actor,
            appointment_id=appointment.sysid,
            starts_at=at(ready, hour, minute),
            expected_revision=appointment.revision,
            **extra,
        )


def status_of(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return service().appointment(actor=actor, appointment_id=appointment.sysid).appointment.status


def test_reschedule_to_another_schedule(ready):
    other = afternoon_schedule(ready)
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


def test_reschedule_to_another_schedule_keeps_the_fit_in(ready, subtests):
    other = afternoon_schedule(ready)
    with subtests.test("a fit-in stays a fit-in, outside the grid of the new schedule"):
        squeezed = book(ready, 12, 30, key="squeezed", fit_in=True)
        moved = move(ready, squeezed, 12, 30, schedule_id=other.sysid)
        assert moved.is_fit_in and moved.schedule_id == other.sysid and moved.starts_at == at(ready, 12, 30)
        assert status_of(ready, squeezed) == "cancelled"
    taken = book(ready, 15, key="taken", schedule_id=other.sysid)
    regular = book(ready, 9, key="regular")
    with subtests.test("a regular one stays regular: the taken slot refuses it and nothing changes"):
        for explicit in ({}, {"fit_in": False}):
            with pytest.raises(Conflict) as error:
                move(ready, regular, 15, schedule_id=other.sysid, **explicit)
            assert error.value.code == "slot_unavailable"
        assert status_of(ready, regular) == "scheduled" and event_of(ready, regular).starts_at == at(ready, 9)
    with subtests.test("an explicit fit-in moves it over the taken slot"):
        moved = move(ready, regular, 15, schedule_id=other.sysid, fit_in=True)
        assert moved.is_fit_in and moved.starts_at == taken.starts_at and moved.rescheduled_from_id == regular.sysid
    with subtests.test("fit_in is a boolean or nothing"), pytest.raises(InvalidInput):
        move(ready, taken, 16, fit_in="yes")


def test_reschedule_in_the_same_schedule_keeps_what_the_appointment_was(ready, subtests):
    first = book(ready, 9, key="first")
    with ready.as_user(ready.a.reception) as actor:
        confirmed = service().confirm(actor=actor, appointment_id=first.sysid, expected_revision=first.revision)
    with subtests.test("code kept, confirmed goes back to scheduled"):
        moved = move(ready, confirmed, 10)
        assert (moved.code, moved.status, moved.is_fit_in) == (first.code, "scheduled", False)
    squeezed = book(ready, 10, key="squeezed", fit_in=True)
    with subtests.test("a fit-in moves over a taken slot and stays a fit-in"):
        book(ready, 11, key="eleven")
        again = move(ready, squeezed, 11)
        assert again.is_fit_in and again.code == squeezed.code and again.starts_at == at(ready, 11)
    with subtests.test("an explicit False makes it regular, so the taken slot refuses it"):
        with pytest.raises(Conflict) as error:
            move(ready, again, 10, fit_in=False)
        assert error.value.code == "slot_unavailable"
        assert not move(ready, again, 8, fit_in=False).is_fit_in
    with subtests.test("an explicit True squeezes a regular one"):
        assert move(ready, moved, 11, fit_in=True).is_fit_in


def test_reschedule_refuses_a_stale_revision_and_a_schedule_it_cannot_change(ready, subtests):
    other = afternoon_schedule(ready)
    read_only = afternoon_schedule(ready, key="read-only", reader_group_ids=(ready.a.groups["reception"],))
    hidden = afternoon_schedule(ready, key="hidden", writer_user_ids=(ready.a.doctor.pk,))
    appointment = book(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        confirmed = service().confirm(
            actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision
        )
    with subtests.test("stale revision"):
        for target in (None, other.sysid):
            with pytest.raises(Conflict) as error:
                move(ready, appointment, 15, schedule_id=target)
            assert error.value.code == "stale_revision"
    with subtests.test("a schedule the actor only reads"), pytest.raises(Forbidden):
        move(ready, confirmed, 15, schedule_id=read_only.sysid)
    with subtests.test("a schedule the actor does not read"), pytest.raises(NotFound):
        move(ready, confirmed, 15, schedule_id=hidden.sysid)
    assert status_of(ready, appointment) == "confirmed" and event_of(ready, appointment).starts_at == at(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        assert service().appointments(actor=actor, schedule_id=other.sysid).items == ()


def lock_order(queries):
    """The tables locked by ``SELECT ... FOR UPDATE``, in order, with the id each lock asked for."""
    found = []
    for query in queries.captured_queries:
        sql = query["sql"]
        if "FOR UPDATE" not in sql or " FROM " not in sql:
            continue
        table = sql.split(" FROM ", 1)[1].split('"')[1]
        if table in ("med_scheduling_schedule", "med_scheduling_appointment"):
            found.append((table.removeprefix("med_scheduling_"), sql))
    return found


def test_reschedule_locks_the_schedules_before_the_appointment(ready, subtests):
    other = afternoon_schedule(ready)
    first, second = sorted((ready.schedule.sysid, other.sysid))
    appointment = book(ready, 9)
    with subtests.test("same schedule"):
        with CaptureQueriesContext(connection) as queries:
            appointment = move(ready, appointment, 10)
        assert [table for table, _sql in lock_order(queries)][:2] == ["schedule", "appointment"]
    for name, target, hour in (("there", other, 15), ("and back", ready.schedule, 11)):
        with subtests.test(f"another schedule: {name}"):
            with CaptureQueriesContext(connection) as queries:
                appointment = move(ready, appointment, hour, schedule_id=target.sysid)
            locks = lock_order(queries)
            assert [table for table, _sql in locks][:3] == ["schedule", "schedule", "appointment"]
            asked = [sql.replace("-", "") for _table, sql in locks[:2]]
            assert first.hex in asked[0] and second.hex in asked[1]


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


def test_day_shows_the_free_slots_of_a_window_restricted_to_a_type(ready):
    with ready.as_user(ready.a.admin) as admin:
        follow_up = service().add_appointment_type(
            actor=admin, code="retorno", name="Retorno", duration_minutes=30, idempotency_key="retorno"
        )
        current = service().schedule(actor=admin, schedule_id=ready.schedule.sysid)
        service().set_availability(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            rules=(
                AvailabilityRuleInput(0, 8 * 60, 9 * 60, date(2026, 1, 1)),
                AvailabilityRuleInput(0, 9 * 60, 10 * 60, date(2026, 1, 1), appointment_type_id=follow_up.sysid),
            ),
            expected_revision=current.revision,
        )
    book(ready, 8, 30)
    with ready.as_user(ready.a.reception) as actor:
        (agenda,) = service().day(actor=actor, date=ready.monday)
    assert [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in agenda.free] == ["08:00", "09:00", "09:30"]


def test_the_appointment_is_paid_for_as_its_kind_says(ready, subtests):
    with ready.as_user(ready.a.admin) as admin:
        insured = service().add_appointment_type(
            actor=admin, code="unimed", name="Unimed", payment_kind="insurance", idempotency_key="unimed"
        )

    def book_insured(hour, **extra):
        with ready.as_user(ready.a.reception) as actor:
            return service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=insured.sysid,
                starts_at=at(ready, hour),
                idempotency_key=f"insured-{hour}",
                **extra,
            )

    with subtests.test("without a payment the appointment takes the one of the kind"):
        inherited = book_insured(8)
        assert inherited.payment_kind == "insurance" and book(ready, 8, 30).payment_kind == "private"
    with subtests.test("a payment given at the booking wins"):
        explicit = book_insured(9, payment_kind="private")
        assert explicit.payment_kind == "private"
    with subtests.test("an unknown payment is refused"):
        with pytest.raises(InvalidInput) as error:
            book_insured(10, payment_kind="voucher")
        assert set(error.value.errors) == {"payment_kind"}
    with subtests.test("the kind changes later and the booked appointments keep theirs"):
        with ready.as_user(ready.a.admin) as admin:
            service().update_appointment_type(
                actor=admin,
                type_id=insured.sysid,
                changes=(("payment_kind", "courtesy"),),
                expected_revision=insured.revision,
            )
        with ready.as_user(ready.a.reception) as actor:
            kept = service().appointment(actor=actor, appointment_id=inherited.sysid).appointment
        assert kept.payment_kind == "insurance" and book_insured(10).payment_kind == "courtesy"
    with subtests.test("moved to another schedule it is paid for as it was"):
        other = afternoon_schedule(ready)
        moved = move(ready, explicit, 14, schedule_id=other.sysid)
        assert (moved.schedule_id, moved.payment_kind) == (other.sysid, "private")
