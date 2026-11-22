"""The kinds of appointment a schedule takes: all without configuration, own duration, refusals, access and CAS."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.service_api import assert_cas_conflict

from ..models import ScheduleAppointmentType
from ..service_api import AvailabilityRuleInput, ScheduleTypeInput, SchedulingService
from .booking import SP, at, prepare
from .helpers import as_admin


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    """The clinic of ``prepare`` (Consulta, 30 min, private) plus Unimed (20 min, insurance)."""
    ready = prepare(clinic)
    with as_admin(ready) as admin:
        ready.insured = service().add_appointment_type(
            actor=admin,
            code="unimed",
            name="Unimed",
            duration_minutes=20,
            payment_kind="insurance",
            idempotency_key="unimed",
        )
    return ready


def revision(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision


def configure(ready, *types, user=None, organization=None, expected_revision=None):
    expected_revision = expected_revision or revision(ready)
    with ready.as_user(user or ready.a.reception, organization or ready.org_a) as actor:
        return service().set_schedule_types(
            actor=actor, schedule_id=ready.schedule.sysid, types=types, expected_revision=expected_revision
        )


def taken(ready, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().schedule_types(actor=actor, schedule_id=ready.schedule.sysid)


def book_kind(ready, kind, hour, minute=0, **extra):
    with ready.as_user(ready.a.reception) as actor:
        return service().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=kind.sysid,
            starts_at=at(ready, hour, minute),
            idempotency_key=f"{kind.code}-{hour}-{minute}",
            **extra,
        )


def free(ready, kind=None, **extra):
    with ready.as_user(ready.a.reception) as actor:
        found = service().available_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            start_date=ready.monday,
            end_date=ready.monday,
            appointment_type_id=kind.sysid if kind else None,
            **extra,
        )
    return [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in found]


def refused(call):
    with pytest.raises(Conflict) as error:
        call()
    return error.value.code


def test_a_schedule_without_configuration_takes_every_active_kind(ready):
    assert [
        (item.appointment_type_id, item.duration_minutes, item.own_duration, item.configured) for item in taken(ready)
    ] == [
        (ready.kind.sysid, 30, None, False),
        (ready.insured.sysid, 20, None, False),
    ]
    assert all(item.allow_booked and item.allow_walk_in for item in taken(ready))
    first = book_kind(ready, ready.kind, 9)
    second = book_kind(ready, ready.insured, 10)
    assert (first.ends_at, second.ends_at) == (at(ready, 9, 30), at(ready, 10, 20))
    with as_admin(ready) as admin:
        service().update_appointment_type(
            actor=admin, type_id=ready.insured.sysid, changes=(("is_active", False),), expected_revision=1
        )
    assert [item.appointment_type_id for item in taken(ready)] == [ready.kind.sysid]
    assert refused(lambda: book_kind(ready, ready.insured, 11)) == "type_not_allowed"
    assert free(ready, ready.insured) == []


def test_configured_kinds_and_the_precedence_of_the_duration(ready, subtests):
    with subtests.test("the schedule's own duration"):
        (only,) = configure(ready, ScheduleTypeInput(ready.insured.sysid, 40))
        assert (only.appointment_type_id, only.duration_minutes, only.own_duration, only.configured) == (
            ready.insured.sysid,
            40,
            40,
            True,
        )
        assert taken(ready) == (only,)
        assert book_kind(ready, ready.insured, 9).ends_at == at(ready, 9, 40)
    with subtests.test("the duration given at the booking wins"):
        assert book_kind(ready, ready.insured, 10, duration_minutes=15).ends_at == at(ready, 10, 15)
    with subtests.test("a kind the schedule does not take, fit-in or not"):
        assert refused(lambda: book_kind(ready, ready.kind, 11)) == "type_not_allowed"
        assert refused(lambda: book_kind(ready, ready.kind, 11, fit_in=True)) == "type_not_allowed"
    with subtests.test("the free slots follow the duration"):
        assert free(ready, ready.insured) == ["08:00", "10:30", "11:00"]
        assert free(ready, ready.insured, duration_minutes=10) == ["08:00", "08:30", "10:30", "11:00", "11:30"]
        assert free(ready, ready.kind) == []
    with subtests.test("without an own duration the kind's is used"):
        (only,) = configure(ready, ScheduleTypeInput(ready.insured.sysid))
        assert (only.duration_minutes, only.own_duration) == (20, None)
        assert book_kind(ready, ready.insured, 11).ends_at == at(ready, 11, 20)
    with subtests.test("a kind taken only by arrival order is not booked with a time"):
        configure(ready, ScheduleTypeInput(ready.insured.sysid, allow_booked=False))
        assert refused(lambda: book_kind(ready, ready.insured, 8)) == "type_not_allowed"
        assert free(ready, ready.insured) == []
    with subtests.test("an empty list takes every kind again"):
        assert [item.configured for item in configure(ready)] == [False, False]
        assert book_kind(ready, ready.kind, 8).ends_at == at(ready, 8, 30)


def rows(ready, *, erased=False):
    """The rows of the table as the database has them: the live ones, or every one ever written."""
    with as_admin(ready):
        return list((ScheduleAppointmentType.all_objects if erased else ScheduleAppointmentType.objects).all())


def test_rows_are_changed_in_place_and_never_erased(ready):
    configure(ready, ScheduleTypeInput(ready.insured.sysid, 40), ScheduleTypeInput(ready.kind.sysid))
    first = {row.appointment_type_id: row.pk for row in rows(ready)}
    configure(ready, ScheduleTypeInput(ready.insured.sysid, 25))
    (kept,) = rows(ready)
    assert (kept.pk, kept.duration_minutes) == (first[ready.insured.sysid], 25)
    assert len(rows(ready, erased=True)) == 2
    configure(ready, ScheduleTypeInput(ready.kind.sysid))
    assert len(rows(ready)) == 1 and len(rows(ready, erased=True)) == 3


def test_refusals(ready, subtests):
    with ready.as_user(ready.b.admin, ready.org_b) as admin:
        foreign = service().add_appointment_type(actor=admin, code="b", name="Da organização B", idempotency_key="b")
    with as_admin(ready) as admin:
        inactive = service().add_appointment_type(actor=admin, code="velho", name="Antigo", idempotency_key="old")
        service().update_appointment_type(
            actor=admin, type_id=inactive.sysid, changes=(("is_active", False),), expected_revision=inactive.revision
        )
    insured = ready.insured.sysid
    cases = {
        "unknown kind": (ScheduleTypeInput(uuid4()),),
        "inactive kind": (ScheduleTypeInput(inactive.sysid),),
        "kind of another organization": (ScheduleTypeInput(foreign.sysid),),
        "the same kind twice": (ScheduleTypeInput(insured), ScheduleTypeInput(insured, 30)),
        "duration below 5": (ScheduleTypeInput(insured, 4),),
        "duration above 480": (ScheduleTypeInput(insured, 481),),
        "duration that is not an integer": (ScheduleTypeInput(insured, "30"),),
        "no mode at all": (ScheduleTypeInput(insured, allow_booked=False, allow_walk_in=False),),
        "not an input": ({"appointment_type_id": insured},),
    }
    before = revision(ready)
    for name, types in cases.items():
        with subtests.test(name), pytest.raises(InvalidInput):
            configure(ready, *types)
    with subtests.test("a list instead of a tuple"), ready.as_user(ready.a.reception) as actor:
        with pytest.raises(InvalidInput):
            service().set_schedule_types(
                actor=actor, schedule_id=ready.schedule.sysid, types=[], expected_revision=before
            )
    assert revision(ready) == before and rows(ready, erased=True) == []
    with subtests.test("booking a kind of another organization"), pytest.raises(NotFound):
        book_kind(ready, foreign, 9)
    with subtests.test("booking and listing with a duration out of range"):
        for minutes in (4, 481):
            with pytest.raises(InvalidInput):
                book_kind(ready, ready.kind, 9, duration_minutes=minutes)
            with pytest.raises(InvalidInput):
                free(ready, ready.kind, duration_minutes=minutes)


def test_authorization_and_isolation(ready, subtests):
    wanted = ScheduleTypeInput(ready.insured.sysid, 40)
    with subtests.test("the professional who owns the schedule changes it"):
        assert [item.own_duration for item in configure(ready, wanted, user=ready.a.doctor)] == [40]
    with subtests.test("who does not read the schedule finds nothing"):
        with pytest.raises(NotFound):
            taken(ready, user=ready.a.finance)
        with pytest.raises(NotFound):
            configure(ready, user=ready.a.finance, expected_revision=1)
    current = revision(ready)
    with as_admin(ready) as admin:
        service().set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            writer_user_ids=(),
            expected_revision=current,
        )
    with subtests.test("a reader lists and does not change"):
        assert [item.own_duration for item in taken(ready, user=ready.a.finance)] == [40]
        with pytest.raises(Forbidden):
            configure(ready, user=ready.a.finance)
    with subtests.test("organization B"):
        with ready.as_user(ready.b.admin, ready.org_b) as actor, pytest.raises(NotFound):
            service().schedule_types(actor=actor, schedule_id=ready.schedule.sysid)
        with pytest.raises(NotFound):
            configure(ready, user=ready.b.admin, organization=ready.org_b, expected_revision=1)
    assert [item.own_duration for item in taken(ready)] == [40]


def test_the_revision_of_the_schedule_is_the_cas(ready, subtests):
    current = revision(ready)

    def save(*types):
        return lambda: configure(ready, *types, expected_revision=current)

    with subtests.test("two savings from the same page"):
        won = assert_cas_conflict(
            save(ScheduleTypeInput(ready.insured.sysid, 40)), save(ScheduleTypeInput(ready.kind.sysid, 50))
        )
        assert [item.own_duration for item in won] == [40] and [item.own_duration for item in taken(ready)] == [40]
    with subtests.test("the grid and the kinds share the revision"), ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict) as error:
            service().set_availability(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),),
                expected_revision=current,
            )
        assert error.value.code == "stale_revision"


def test_booked_appointments_keep_what_they_were(ready):
    booked = book_kind(ready, ready.insured, 9)
    configure(ready, ScheduleTypeInput(ready.kind.sysid))
    with ready.as_user(ready.a.reception) as actor:
        moved = service().reschedule(
            actor=actor, appointment_id=booked.sysid, starts_at=at(ready, 10), expected_revision=booked.revision
        )
    assert (moved.appointment_type_id, moved.ends_at - moved.starts_at) == (ready.insured.sysid, timedelta(minutes=20))
