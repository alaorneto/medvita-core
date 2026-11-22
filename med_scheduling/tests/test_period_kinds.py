"""The kinds of each period of the weekly grid: the grid is compared with what exists, the single kind of an
older row is still read, slots and bookings follow the period, and what is refused."""

from datetime import date
from uuid import uuid4

import pytest

from skeleton.service_api import Conflict, InvalidInput, NotFound
from skeleton.testing.service_api import assert_cas_conflict

from ..models import AvailabilityRule, AvailabilityRuleType
from ..service_api import AvailabilityRuleInput, ScheduleTypeInput, SchedulingService
from .booking import SP, at, prepare
from .helpers import as_admin

START = date(2026, 1, 1)


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    """The clinic of ``prepare`` (Consulta, 30 min) plus Unimed (20 min) and Retorno (30 min)."""
    ready = prepare(clinic)
    with as_admin(ready) as admin:
        ready.insured = service().add_appointment_type(
            actor=admin, code="unimed", name="Unimed", duration_minutes=20, idempotency_key="unimed"
        )
        ready.follow_up = service().add_appointment_type(
            actor=admin, code="retorno", name="Retorno", duration_minutes=30, idempotency_key="retorno"
        )
    return ready


def revision(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision


def period(start, end, *kinds, weekday=0, **extra):
    """A period in whole hours of a Monday (or ``weekday``) with the kinds it takes."""
    return AvailabilityRuleInput(
        weekday, start * 60, end * 60, START, appointment_type_ids=tuple(kind.sysid for kind in kinds), **extra
    )


def save(ready, *rules, user=None, organization=None, expected_revision=None):
    expected_revision = expected_revision or revision(ready)
    with ready.as_user(user or ready.a.reception, organization or ready.org_a) as actor:
        return service().set_availability(
            actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=expected_revision
        )


def take(ready, *kinds):
    """Configure the schedule to take only these kinds."""
    current = revision(ready)
    with ready.as_user(ready.a.reception) as actor:
        service().set_schedule_types(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            types=tuple(ScheduleTypeInput(kind.sysid) for kind in kinds),
            expected_revision=current,
        )


def grid(ready, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().availability(actor=actor, schedule_id=ready.schedule.sysid)


def ids(*kinds):
    return tuple(sorted((kind.sysid for kind in kinds), key=str))


def rows(ready, model, *, erased=False):
    """The rows of a table as the database has them: the live ones, or every one ever written."""
    with as_admin(ready):
        return list((model.all_objects if erased else model.objects).all())


def stamps(ready):
    """Identity and revision of every row ever written to the grid and to the kinds of its periods."""
    return {
        (model.__name__, row.pk): (row.revision, row.deleted_at)
        for model in (AvailabilityRule, AvailabilityRuleType)
        for row in rows(ready, model, erased=True)
    }


def free(ready, kind=None, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().available_slots(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            start_date=ready.monday,
            end_date=ready.monday,
            appointment_type_id=kind.sysid if kind else None,
        )


def hours(slots):
    return [slot.starts_at.astimezone(SP).strftime("%H:%M") for slot in slots]


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


def refused(call):
    with pytest.raises(Conflict) as error:
        call()
    return error.value.code


def invalid(call):
    with pytest.raises(InvalidInput) as error:
        call()
    return set(error.value.errors)


def test_a_period_lists_the_kinds_it_takes(ready, subtests):
    with subtests.test("several kinds, and none"):
        both, every = save(ready, period(8, 10, ready.insured, ready.kind), period(10, 12))
        assert both.appointment_type_ids == ids(ready.insured, ready.kind) and both.appointment_type_id is None
        assert every.appointment_type_ids == () and every.appointment_type_id is None
        assert grid(ready) == (both, every)
    with subtests.test("a single kind still answers by the older name"):
        (only,) = save(ready, period(8, 10, ready.insured))
        assert (only.appointment_type_id, only.appointment_type_ids) == (ready.insured.sysid, (ready.insured.sysid,))
    with subtests.test("the older name of a single kind joins the set"):
        (joined,) = save(ready, period(8, 10, ready.kind, appointment_type_id=ready.insured.sysid))
        assert joined.appointment_type_ids == ids(ready.insured, ready.kind)
        (repeated,) = save(ready, period(8, 10, ready.insured, appointment_type_id=ready.insured.sysid))
        assert repeated.appointment_type_ids == (ready.insured.sysid,)
    with subtests.test("the positional calls of before"):
        plain = AvailabilityRuleInput(0, 8 * 60, 12 * 60, START)
        named = AvailabilityRuleInput(1, 8 * 60, 12 * 60, START, None, ready.follow_up.sysid)
        assert (plain.appointment_type_id, plain.appointment_type_ids, named.appointment_type_ids) == (None, (), ())
        first, second = save(ready, named, plain)
        assert (first.weekday, first.appointment_type_ids) == (0, ())
        assert (second.weekday, second.appointment_type_id) == (1, ready.follow_up.sysid)
    with subtests.test("the professional of the schedule reads the same"):
        assert grid(ready, ready.a.doctor) == grid(ready)
    with subtests.test("another organization reads nothing"):
        with ready.as_user(ready.b.reception, ready.org_b) as actor, pytest.raises(NotFound):
            service().availability(actor=actor, schedule_id=ready.schedule.sysid)


def test_saving_the_same_grid_writes_only_the_revision_of_the_schedule(ready):
    first = save(ready, period(8, 10, ready.insured, ready.kind), period(10, 12), period(8, 12, weekday=2))
    before, schedule_revision = stamps(ready), revision(ready)
    again = save(ready, period(8, 12, weekday=2), period(10, 12), period(8, 10, ready.kind, ready.insured))
    assert again == first and stamps(ready) == before
    assert revision(ready) != schedule_revision


def test_only_what_changed_is_written_and_nothing_is_erased(ready, subtests):
    early, late = save(ready, period(8, 10, ready.insured, ready.kind), period(10, 12))
    links = {row.appointment_type_id: row.pk for row in rows(ready, AvailabilityRuleType)}
    assert set(links) == {ready.insured.sysid, ready.kind.sysid}
    with subtests.test("a kind leaves the period and another comes in"):
        before = stamps(ready)
        changed, same = save(ready, period(8, 10, ready.insured, ready.follow_up), period(10, 12))
        assert (changed.sysid, same) == (early.sysid, late)
        assert changed.appointment_type_ids == ids(ready.insured, ready.follow_up)
        live = {row.appointment_type_id: row.pk for row in rows(ready, AvailabilityRuleType)}
        assert set(live) == {ready.insured.sysid, ready.follow_up.sysid}
        assert live[ready.insured.sysid] == links[ready.insured.sysid]
        after = stamps(ready)
        # The two windows and the kind that stayed were not written; the kind that left keeps its row, erased.
        untouched = [("AvailabilityRule", early.sysid), ("AvailabilityRule", late.sysid)]
        untouched.append(("AvailabilityRuleType", links[ready.insured.sysid]))
        assert all(after[key] == before[key] for key in untouched)
        assert after[("AvailabilityRuleType", links[ready.kind.sysid])][1] is not None
    with subtests.test("other hours are another window"):
        kept, moved = save(ready, period(8, 10, ready.insured, ready.follow_up), period(10, 11))
        assert kept.sysid == early.sysid and moved.sysid != late.sysid
        assert stamps(ready)[("AvailabilityRule", late.sysid)][1] is not None
    with subtests.test("a period back to every kind keeps its window"):
        (opened, _moved) = save(ready, period(8, 10), period(10, 11))
        assert (opened.sysid, opened.appointment_type_ids) == (early.sysid, ())
        assert rows(ready, AvailabilityRuleType) == []
    with subtests.test("a window leaves with its kinds, the kinds first"):
        save(ready, period(8, 10, ready.insured), period(10, 11))
        (left,) = save(ready, period(10, 11))
        assert left.appointment_type_ids == ()
        assert rows(ready, AvailabilityRuleType) == [] and len(rows(ready, AvailabilityRule)) == 1
        erased = rows(ready, AvailabilityRuleType, erased=True)
        assert len(erased) == 4 and all(row.deleted_at is not None for row in erased)
        assert len(rows(ready, AvailabilityRule, erased=True)) == 4


def test_the_single_kind_of_an_older_row_is_still_read(ready, subtests):
    save(ready)
    with as_admin(ready):
        older = AvailabilityRule(
            organization_id=ready.org_a.pk,
            schedule_id=ready.schedule.sysid,
            weekday=0,
            start_minute=8 * 60,
            end_minute=10 * 60,
            valid_from=START,
            appointment_type_id=ready.follow_up.sysid,
        )
        older.save()

    def stored():
        (row,) = rows(ready, AvailabilityRule)
        return row.pk, row.appointment_type_id, row.revision

    with subtests.test("read as a period of that kind"):
        (only,) = grid(ready)
        assert (only.sysid, only.appointment_type_id) == (older.pk, ready.follow_up.sysid)
        assert only.appointment_type_ids == (ready.follow_up.sysid,)
    with subtests.test("slots and bookings follow it"):
        assert hours(free(ready, ready.follow_up)) == ["08:00", "08:30", "09:00", "09:30"]
        assert hours(free(ready, ready.kind)) == []
        assert refused(lambda: book_kind(ready, ready.kind, 8)) == "slot_unavailable"
        assert book_kind(ready, ready.follow_up, 8).starts_at == at(ready, 8)
    with subtests.test("saved back as it was read, the row is not written"):
        before = stored()
        (same,) = save(ready, period(8, 10, ready.follow_up))
        assert same.appointment_type_ids == (ready.follow_up.sysid,) and stored() == before
        assert rows(ready, AvailabilityRuleType) == []
    with subtests.test("when the kinds change, the single kind moves to the kinds of the period"):
        (changed,) = save(ready, period(8, 10, ready.follow_up, ready.insured))
        assert changed.sysid == older.pk and changed.appointment_type_ids == ids(ready.follow_up, ready.insured)
        assert stored()[1] is None
        assert {row.appointment_type_id for row in rows(ready, AvailabilityRuleType)} == {
            ready.follow_up.sysid,
            ready.insured.sysid,
        }
    with subtests.test("and a period without kinds clears it"):
        with as_admin(ready):
            AvailabilityRule(
                organization_id=ready.org_a.pk,
                schedule_id=ready.schedule.sysid,
                weekday=3,
                start_minute=8 * 60,
                end_minute=10 * 60,
                valid_from=START,
                appointment_type_id=ready.follow_up.sysid,
            ).save()
        _monday, thursday = save(ready, period(8, 10, ready.follow_up, ready.insured), period(8, 10, weekday=3))
        assert thursday.appointment_type_ids == () and thursday.appointment_type_id is None
        with as_admin(ready):
            assert AvailabilityRule.objects.get(pk=thursday.sysid).appointment_type_id is None


def test_slots_and_bookings_follow_the_kinds_of_the_period(ready, subtests):
    save(ready, period(8, 10, ready.insured, ready.follow_up), period(10, 12))
    restricted = ids(ready.insured, ready.follow_up)
    with subtests.test("a kind of the period sees both periods, and each slot says the kinds of its own"):
        found = free(ready, ready.follow_up)
        assert hours(found) == ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]
        assert [slot.appointment_type_ids for slot in found] == [restricted] * 4 + [()] * 4
    with subtests.test("another kind, or none, sees only the period of every kind"):
        assert hours(free(ready, ready.kind)) == hours(free(ready)) == ["10:00", "10:30", "11:00", "11:30"]
    with subtests.test("the day shows every period with its kinds"):
        with ready.as_user(ready.a.reception) as actor:
            (agenda,) = service().day(actor=actor, date=ready.monday)
        assert hours(agenda.free)[:5] == ["08:00", "08:30", "09:00", "09:30", "10:00"]
        assert [slot.appointment_type_ids for slot in agenda.free] == [restricted] * 4 + [()] * 4
    with subtests.test("booking a kind the period does not take"):
        assert refused(lambda: book_kind(ready, ready.kind, 8)) == "slot_unavailable"
        assert refused(lambda: book_kind(ready, ready.kind, 9, 30, duration_minutes=60)) == "slot_unavailable"
    with subtests.test("booking a kind of the period, and any kind in the open one"):
        assert book_kind(ready, ready.insured, 8).ends_at == at(ready, 8, 20)
        assert book_kind(ready, ready.kind, 10).ends_at == at(ready, 10, 30)
    with subtests.test("a fit-in skips the kinds of the period"):
        assert book_kind(ready, ready.kind, 9, fit_in=True).is_fit_in
    with subtests.test("and never the kinds of the schedule"):
        take(ready, ready.insured, ready.follow_up)
        assert refused(lambda: book_kind(ready, ready.kind, 9, 30, fit_in=True)) == "type_not_allowed"
        assert refused(lambda: book_kind(ready, ready.kind, 11)) == "type_not_allowed"
        assert book_kind(ready, ready.follow_up, 11).starts_at == at(ready, 11)


def test_the_kinds_of_a_new_period_are_ones_the_schedule_takes(ready, subtests):
    with as_admin(ready, ready.b) as admin:
        foreign = service().add_appointment_type(actor=admin, code="fora", name="De fora", idempotency_key="fora")
    before = grid(ready)

    def unknown(*rules):
        return invalid(lambda: save(ready, *rules))

    with subtests.test("of another organization"):
        assert unknown(period(13, 14, foreign)) == {"appointment_type_ids"}
    with subtests.test("that does not exist"):
        assert unknown(AvailabilityRuleInput(0, 780, 840, START, appointment_type_ids=(uuid4(),))) == {
            "appointment_type_ids"
        }
        assert unknown(AvailabilityRuleInput(0, 780, 840, START, appointment_type_id=uuid4())) == {
            "appointment_type_ids"
        }
    with subtests.test("that is not a list of identifiers"):
        assert unknown(AvailabilityRuleInput(0, 780, 840, START, appointment_type_ids="unimed")) == {
            "appointment_type_ids"
        }
        assert unknown(AvailabilityRuleInput(0, 780, 840, START, appointment_type_ids=("unimed",))) == {
            "appointment_type_ids"
        }
    with subtests.test("inactive"):
        with as_admin(ready) as admin:
            service().update_appointment_type(
                actor=admin, type_id=ready.follow_up.sysid, changes=(("is_active", False),), expected_revision=1
            )
        assert unknown(period(13, 14, ready.follow_up)) == {"appointment_type_ids"}
    assert grid(ready) == before
    with subtests.test("one the schedule stopped taking stays where it was and enters nowhere else"):
        listed, _open = save(ready, period(8, 10, ready.insured), period(10, 12))
        take(ready, ready.kind)
        assert unknown(period(8, 10, ready.insured), period(10, 12), period(13, 14, ready.insured)) == {
            "appointment_type_ids"
        }
        assert unknown(period(8, 10, ready.insured), period(10, 12, ready.insured)) == {"appointment_type_ids"}
        kept, new = save(ready, period(8, 10, ready.insured), period(13, 14, ready.kind))
        assert (kept.sysid, kept.appointment_type_ids) == (listed.sysid, (ready.insured.sysid,))
        assert new.appointment_type_ids == (ready.kind.sysid,)
        # A kind that stays may be joined by one the schedule takes; only what comes in is checked.
        (joined, _new) = save(ready, period(8, 10, ready.insured, ready.kind), period(13, 14, ready.kind))
        assert joined.appointment_type_ids == ids(ready.insured, ready.kind)


def test_the_grid_is_refused_whole(ready, subtests):
    before, stamped = grid(ready), stamps(ready)
    with subtests.test("more than 100 periods"):
        many = tuple(
            AvailabilityRuleInput(index % 7, 60 * (index // 7), 60 * (index // 7) + 30, START) for index in range(101)
        )
        assert invalid(lambda: save(ready, *many)) == {"rules"}
        assert len(save(ready, *many[:100])) == 100
        save(ready, period(8, 12))
        before, stamped = grid(ready), stamps(ready)
    with subtests.test("two periods over each other"):
        assert invalid(lambda: save(ready, period(8, 10, ready.insured), period(9, 11))) == {"rules"}
    with subtests.test("a page that opened before another change"):
        current = revision(ready)
        won = assert_cas_conflict(
            lambda: save(ready, period(8, 9, ready.insured), expected_revision=current),
            lambda: save(ready, period(9, 10, ready.kind), expected_revision=current),
        )
        assert grid(ready) == won
        before, stamped = grid(ready), stamps(ready)
    with subtests.test("who does not write the schedule"):
        with pytest.raises(NotFound):
            save(ready, period(8, 9), user=ready.a.finance)
        with pytest.raises(NotFound):
            save(ready, period(8, 9), user=ready.b.reception, organization=ready.org_b)
    assert grid(ready) == before and stamps(ready) == stamped
