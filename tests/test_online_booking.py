"""Online booking from the patient portal: only what a schedule published, only for a linked patient.

The portal app is the reference app (``med_example``): it admits the person and links the patient
through ``register_portal_patients``; the agenda books through its ``allow_external`` methods.
"""

from contextlib import contextmanager
from datetime import timedelta

import pytest

from applications.med_example.apps import PORTAL_LINKS
from applications.med_scheduling.service_api import SchedulingService
from applications.med_scheduling.tests.booking import at, prepare
from applications.med_scheduling.tests.helpers import as_admin, new_patient
from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.service_api import Conflict, Forbidden, NotFound
from skeleton.service_api.external import ExternalAccessService
from skeleton.testing.applications import activate_app, open_app
from skeleton.testing.events import capture_events
from skeleton.testing.external import acting_external, assert_external_contract
from tests.support import portal_scenario, with_new_outsider


@pytest.fixture
def ready(clinic):
    prepared = prepare(clinic)
    service = SchedulingService()
    with as_admin(clinic) as admin:
        service.update_appointment_type(
            actor=admin,
            type_id=prepared.kind.sysid,
            changes=(("online_booking", True),),
            expected_revision=prepared.kind.revision,
        )
    with clinic.as_user(clinic.a.reception) as actor:
        schedule = service.schedule(actor=actor, schedule_id=prepared.schedule.sysid)
        service.set_online_booking(
            actor=actor,
            schedule_id=schedule.sysid,
            enabled=True,
            min_notice_hours=0,
            horizon_days=60,
            expected_revision=schedule.revision,
        )
    open_app("med_example")
    for organization in (clinic.org_a, clinic.org_b):
        activate_app("med_example", organization.pk)
    prepared.scenario = portal_scenario(clinic, "med_example")
    prepared.other = new_patient(clinic, full_name="Outro Paciente")
    PORTAL_LINKS.clear()
    for user in (prepared.scenario.external, prepared.scenario.dual):
        with acting_external(user, clinic.org_a) as actor:
            PORTAL_LINKS[ExternalAccessService().me(actor=actor).sysid] = (prepared.patient.sysid,)
    yield prepared
    PORTAL_LINKS.clear()


@contextmanager
def portal(ready, user=None):
    with acting_external(user or ready.scenario.external, ready.org_a) as actor:
        yield actor


def _book(ready, hour, *, key="online", patient=None, user=None, minute=0):
    with portal(ready, user) as actor:
        return SchedulingService().book_external(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            patient_id=(patient or ready.patient).sysid,
            starts_at=at(ready, hour, minute),
            idempotency_key=key,
        )


def test_the_portal_sees_and_books_only_what_was_published(ready):
    service = SchedulingService()
    with portal(ready) as actor:
        (published,) = service.public_schedules(actor=actor)
        slots = service.public_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            start_date=ready.monday,
            end_date=ready.monday,
        )
    assert published.sysid == ready.schedule.sysid and published.professional_name == "Dra. Ana"
    assert [kind.sysid for kind in published.types] == [ready.kind.sysid]
    assert at(ready, 9) in [slot.starts_at for slot in slots] and len(slots) == 8
    with capture_events() as events:
        booked = _book(ready, 9)
    assert (booked.status, booked.booked_online, booked.patient_id) == ("scheduled", True, ready.patient.sysid)
    assert booked.code.startswith("A") and booked.starts_at == at(ready, 9)
    (event,) = [item for item in events if item.event_type == "med_scheduling.appointment_booked"]
    assert dict(event.data)["patient"] == str(ready.patient.sysid)
    assert _book(ready, 9).sysid == booked.sysid  # The same key gives the same appointment.
    with portal(ready) as actor:
        left = service.public_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            start_date=ready.monday,
            end_date=ready.monday,
        )
    assert at(ready, 9) not in [slot.starts_at for slot in left]
    with ready.as_user(ready.a.reception) as actor:
        seen = service.appointment(actor=actor, appointment_id=booked.sysid).appointment
    with ready.as_user(ready.a.doctor) as actor:  # The owner of the schedule's calendar sees the title.
        event_in_calendar = CalendarService().managed_event(
            actor=actor, source_app="med_scheduling", source_key=str(booked.sysid)
        )
    assert seen.booked_online and event_in_calendar.title == f"Consulta · {booked.code}"


def test_a_schedule_or_kind_not_published_is_not_there(ready):
    service = SchedulingService()
    with ready.as_user(ready.a.reception) as actor:
        schedule = service.schedule(actor=actor, schedule_id=ready.schedule.sysid)
        service.set_online_booking(
            actor=actor, schedule_id=schedule.sysid, enabled=False, expected_revision=schedule.revision
        )
    with portal(ready) as actor:
        assert service.public_schedules(actor=actor) == ()
        with pytest.raises(NotFound):
            service.public_slots(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                appointment_type_id=ready.kind.sysid,
                start_date=ready.monday,
                end_date=ready.monday,
            )
    with pytest.raises(NotFound):
        _book(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        schedule = service.schedule(actor=actor, schedule_id=ready.schedule.sysid)
        service.set_online_booking(
            actor=actor,
            schedule_id=schedule.sysid,
            enabled=True,
            min_notice_hours=0,
            expected_revision=schedule.revision,
        )
    with as_admin(ready) as admin:
        kind = next(item for item in service.appointment_types(actor=admin) if item.sysid == ready.kind.sysid)
        service.update_appointment_type(
            actor=admin, type_id=kind.sysid, changes=(("online_booking", False),), expected_revision=kind.revision
        )
    with portal(ready) as actor:
        assert service.public_schedules(actor=actor) == ()
    with pytest.raises(NotFound):
        _book(ready, 9)


def test_two_requests_for_the_same_time_one_wins(ready):
    _book(ready, 10, key="first")
    with pytest.raises(Conflict) as error:
        _book(ready, 10, key="second", user=ready.scenario.dual)
    assert error.value.code == "slot_unavailable"
    with pytest.raises(Conflict) as outside:
        _book(ready, 7, key="before-the-grid")
    assert outside.value.code == "slot_unavailable"


def test_the_person_never_books_for_an_unlinked_patient_and_the_rate_is_limited(ready):
    with pytest.raises(NotFound):
        _book(ready, 9, patient=ready.other)
    for index, hour in enumerate((8, 9, 10)):
        _book(ready, hour, key=f"rate-{index}")
    with pytest.raises(Conflict) as error:
        _book(ready, 11, key="rate-3")
    assert error.value.code == "rate_limited"


def test_the_notice_and_the_horizon_bound_the_offer(ready):
    service = SchedulingService()
    with ready.as_user(ready.a.reception) as actor:
        schedule = service.schedule(actor=actor, schedule_id=ready.schedule.sysid)
        service.set_online_booking(
            actor=actor, schedule_id=schedule.sysid, enabled=True, horizon_days=1, expected_revision=schedule.revision
        )
    with portal(ready) as actor:
        slots = service.public_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            start_date=ready.monday,
            end_date=ready.monday + timedelta(days=7),
        )
    assert slots == ()  # Monday is more than one day ahead.


def test_the_portal_contract_of_each_method(ready):
    service = SchedulingService()
    keys = iter(range(100))

    def booking(actor):
        return service.book_external(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            patient_id=ready.patient.sysid,
            starts_at=at(ready, 11, 30),
            idempotency_key=f"contract-{next(keys)}",
        )

    def slots(actor):
        return service.public_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            start_date=ready.monday,
            end_date=ready.monday,
        )

    for method, call in (
        ("public_schedules", lambda actor: service.public_schedules(actor=actor)),
        ("public_slots", slots),
    ):
        assert_external_contract(
            SchedulingService,
            method,
            scenario=with_new_outsider(ready.scenario, method),
            call=call,
            unlinked=lambda result: not result,
            disabled=lambda: ready.app_disabled("med_scheduling"),
        )
    assert_external_contract(
        SchedulingService,
        "book_external",
        scenario=with_new_outsider(ready.scenario, "book_external"),
        call=booking,
        unlinked=lambda result: result is None,
        disabled=lambda: ready.app_disabled("med_scheduling"),
    )
    with ready.as_user(ready.a.reception) as member, pytest.raises(Forbidden):
        service.book_external(
            actor=member,
            schedule_id=ready.schedule.sysid,
            appointment_type_id=ready.kind.sysid,
            patient_id=ready.patient.sysid,
            starts_at=at(ready, 9),
            idempotency_key="member",
        )


def test_the_pages_publish_the_schedule_and_offer_the_kind(ready):
    from django.test import Client
    from django.urls import reverse

    service = SchedulingService()
    org = ready.org_a.pk
    reception = Client()
    reception.force_login(ready.a.reception)
    page = reception.get(reverse("med_scheduling:schedule-online", args=(org, ready.schedule.sysid))).content.decode()
    assert "Agendamento online" in page and "Publicada no portal do paciente" in page
    with ready.as_user(ready.a.reception) as actor:
        current = service.schedule(actor=actor, schedule_id=ready.schedule.sysid)
    response = reception.post(
        reverse("med_scheduling:schedule-online", args=(org, ready.schedule.sysid)),
        {"min_notice_hours": "48", "horizon_days": "15", "revision": current.revision},
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        changed = service.schedule(actor=actor, schedule_id=ready.schedule.sysid)
    assert (changed.online_booking, changed.online_min_notice_hours, changed.online_horizon_days) == (False, 48, 15)
    admin = Client()
    admin.force_login(ready.a.admin)
    edit = reverse("med_scheduling:type-edit", args=(org, ready.kind.sysid))
    assert "Oferecer no agendamento online" in admin.get(edit).content.decode()
    outsider = Client()
    outsider.force_login(ready.b.reception)
    address = reverse("med_scheduling:schedule-online", args=(ready.org_b.pk, ready.schedule.sysid))
    assert (
        outsider.post(
            address, {"enabled": "on", "min_notice_hours": "0", "horizon_days": "1", "revision": 1}
        ).status_code
        == 404
    )
