"""The reception flow: confirm, check in (the professional is told), start, complete, no-show, actions."""

from datetime import timedelta

import pytest
from django.utils import timezone

from skeleton.service_api import Conflict
from skeleton.service_api.notifications import NotificationService
from skeleton.testing.events import capture_events
from skeleton.testing.jobs import run_pending_jobs

from ..extension import AppointmentAction, isolated_actions, register_appointment_action
from ..service_api import SchedulingService
from .booking import book, prepare


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def step(ready, name, appointment, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return getattr(service(), name)(
            actor=actor, appointment_id=appointment.sysid, expected_revision=appointment.revision
        )


def test_the_happy_path_publishes_each_state(ready):
    appointment = book(ready, 9)
    with capture_events() as events:
        appointment = step(ready, "confirm", appointment)
        appointment = step(ready, "check_in", appointment)
        appointment = step(ready, "start", appointment, user=ready.a.doctor)
        appointment = step(ready, "complete", appointment, user=ready.a.doctor)
    assert [event.event_type.rsplit(".", 1)[1] for event in events] == [
        "appointment_confirmed",
        "appointment_arrived",
        "appointment_started",
        "appointment_completed",
    ]
    assert [dict(event.data)["status"] for event in events] == ["confirmed", "arrived", "in_progress", "completed"]
    with ready.as_user(ready.a.reception) as actor:
        detail = service().appointment(actor=actor, appointment_id=appointment.sysid)
    assert detail.arrived_at and detail.started_at and detail.completed_at
    with pytest.raises(Conflict) as error:
        step(ready, "confirm", appointment)
    assert error.value.code == "invalid_transition"


def test_stale_revision(ready):
    appointment = book(ready, 9)
    step(ready, "confirm", appointment)
    with pytest.raises(Conflict) as error:
        step(ready, "check_in", appointment)
    assert error.value.code == "stale_revision"


def test_no_show_only_after_the_start(ready):
    future = book(ready, 9)
    with pytest.raises(Conflict):
        step(ready, "mark_no_show", future)
    past_start = timezone.now() - timedelta(hours=2)
    with ready.as_user(ready.a.reception) as actor:
        past = service().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            starts_at=past_start,
            fit_in=True,
            idempotency_key="past",
        )
    assert step(ready, "mark_no_show", past).status == "no_show"


def test_arrival_notifies_the_professional_once(ready):
    appointment = book(ready, 9)
    arrived = step(ready, "check_in", appointment)
    run_pending_jobs()
    with ready.as_user(ready.a.doctor) as actor:
        inbox = NotificationService().inbox(actor=actor).items
    assert [item.type_code for item in inbox] == ["med_scheduling.patient_arrived"]
    values = {value.name: value.value for value in inbox[0].payload}
    assert values["code"] == appointment.code and "Maria" not in str(values)
    with ready.as_user(ready.a.reception) as actor:
        assert NotificationService().inbox(actor=actor).items == ()
    assert arrived.status == "arrived"


def test_actions_of_active_apps_for_the_state(ready):
    appointment = book(ready, 9)
    with isolated_actions() as actions:
        actions.clear()  # Start without the actions the installed apps registered.
        register_appointment_action(
            AppointmentAction("med_scheduling.extra", "Extra", "med_scheduling:home", statuses=("arrived",), order=5)
        )
        actions["med_patients.peek"] = AppointmentAction(
            "med_patients.peek", "Espiar", "med_patients:list", statuses=("scheduled", "arrived"), order=1
        )
        with ready.as_user(ready.a.reception) as actor:
            assert [
                item.code for item in service().appointment_actions(actor=actor, appointment_id=appointment.sysid)
            ] == ["med_patients.peek"]
        arrived = step(ready, "check_in", appointment)
        with ready.as_user(ready.a.reception) as actor:
            codes = [item.code for item in service().appointment_actions(actor=actor, appointment_id=arrived.sysid)]
        assert codes == ["med_patients.peek", "med_scheduling.extra"]
        with pytest.raises(ValueError):
            register_appointment_action(AppointmentAction("med_records.attend", "X", "x", statuses=("arrived",)))


# ------------------------------------------------------------------ undo the arrival (#129)


def give_finance_read(ready):
    """Finance reads the schedule without writing it."""
    from skeleton.service_api import Forbidden  # noqa: F401  (the error the reader gets)

    with ready.as_user(ready.a.admin) as admin:
        current = service().schedule(actor=admin, schedule_id=ready.schedule.sysid)
        service().set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            expected_revision=current.revision,
        )


def test_the_window_to_undo_an_arrival_is_the_service_s():
    from ..service_api import CHECK_IN_UNDO_MINUTES
    from ..transitions import undo_target

    assert 0 < CHECK_IN_UNDO_MINUTES <= 15
    assert undo_target(confirmed=True) == "confirmed" and undo_target(confirmed=False) == "scheduled"


def test_undoing_an_arrival_goes_back_to_the_state_before_it(ready, subtests):
    from skeleton.service_api.audit import AuditService

    with subtests.test("from a scheduled appointment"):
        arrived = step(ready, "check_in", book(ready, 9))
        assert arrived.arrived_at is not None
        with capture_events() as events:
            back = step(ready, "undo_check_in", arrived)
        assert (back.status, back.arrived_at) == ("scheduled", None)
        (event,) = events
        assert event.event_type == "med_scheduling.appointment_arrival_undone"
        assert dict(event.data)["status"] == "scheduled" and "Maria" not in str(event.data)
        with ready.as_user(ready.a.reception) as actor:
            assert service().appointment(actor=actor, appointment_id=back.sysid).arrived_at is None
        with ready.as_user(ready.a.admin) as admin:
            history = (
                AuditService().history(actor=admin, table_key="med_scheduling.appointment", record_id=back.sysid).items
            )
        changed = {change.name: (change.old, change.new) for change in history[0].changes}
        assert changed["status"] == ("arrived", "scheduled") and changed["arrived_at"][1] is None
    with subtests.test("from a confirmed appointment"):
        confirmed = step(ready, "confirm", book(ready, 10))
        back = step(ready, "undo_check_in", step(ready, "check_in", confirmed))
        assert back.status == "confirmed"
        assert step(ready, "check_in", back).status == "arrived"  # And the patient can arrive again.
    with subtests.test("only who is waiting"):
        with pytest.raises(Conflict) as error:
            step(ready, "undo_check_in", book(ready, 11))
        assert error.value.code == "invalid_transition"


def test_an_arrival_is_not_undone_after_the_window(ready, monkeypatch):
    from ..service_api import CHECK_IN_UNDO_MINUTES

    arrived = step(ready, "check_in", book(ready, 9))
    later = timezone.now() + timedelta(minutes=CHECK_IN_UNDO_MINUTES, seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: later)
    with pytest.raises(Conflict) as error:
        step(ready, "undo_check_in", arrived)
    assert error.value.code == "undo_expired" and "minutos" in str(error.value.detail)
    with ready.as_user(ready.a.reception) as actor:
        assert service().appointment(actor=actor, appointment_id=arrived.sysid).appointment.status == "arrived"


def test_who_cannot_register_the_arrival_does_not_undo_it(ready, subtests):
    from skeleton.service_api import Forbidden, NotFound

    arrived = step(ready, "check_in", book(ready, 9))
    with subtests.test("a reader of the schedule"):
        give_finance_read(ready)
        with pytest.raises(Forbidden):
            step(ready, "undo_check_in", arrived, user=ready.a.finance)
    with subtests.test("another organization"):
        with ready.as_user(ready.b.reception, ready.org_b) as actor, pytest.raises(NotFound):
            service().undo_check_in(actor=actor, appointment_id=arrived.sysid, expected_revision=arrived.revision)
    with subtests.test("a stale page"):
        with pytest.raises(Conflict) as error:
            with ready.as_user(ready.a.reception) as actor:
                service().undo_check_in(actor=actor, appointment_id=arrived.sysid, expected_revision=1)
        assert error.value.code == "stale_revision"
    with ready.as_user(ready.a.reception) as actor:
        assert service().appointment(actor=actor, appointment_id=arrived.sysid).appointment.status == "arrived"
