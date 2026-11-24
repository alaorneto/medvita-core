"""Practice, professionals, rooms and appointment types: configuration derived from the practice."""

from itertools import count

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import assert_cas_conflict, assert_service_contract, build_service_scenario

from ..models import AppointmentType, Practice, Professional, Room
from ..service_api import SchedulingService
from .helpers import as_admin, setup_patients, setup_practice

REQUIRED_APPS = ("med_patients",)


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    setup_patients(clinic)
    setup_practice(clinic)
    return clinic


def test_service_contract():
    assert_service_contract(SchedulingService)


@pytest.mark.parametrize("model", [Professional, Room, AppointmentType])
def test_configuration_follows_the_practice(skeleton_db, model):
    for label in (*REQUIRED_APPS, "med_scheduling"):
        open_app(label)
    scenario = build_service_scenario(model, slug=f"practice-{model._meta.model_name}")
    numbers = count(1)

    def make_practice(*, organization, owner):
        practice = Practice(organization=organization, owner=owner, visibility="private", name=f"C{next(numbers)}")
        practice.save()
        return practice

    def make_row(practice):
        values = {"organization": practice.organization, "practice": practice}
        if model is Professional:
            row = Professional(display_name="Dra. Ana", **values)
        elif model is Room:
            row = Room(name="Sala 1", **values)
        else:
            row = AppointmentType(code=f"t{next(numbers)}", name="Consulta", **values)
        row.save()
        return row

    assert_derived_access_contract(child_model=model, make_anchor=make_practice, make_child=make_row, scenario=scenario)


def test_setup_once_and_only_by_the_administrator(clinic):
    setup_patients(clinic)
    with clinic.as_user(clinic.a.reception) as actor, pytest.raises(Forbidden):
        service().setup(actor=actor, practice_name="X", idempotency_key="k")
    first = setup_practice(clinic)
    assert setup_practice(clinic).sysid == first.sysid
    with as_admin(clinic) as admin:
        with pytest.raises(Conflict):
            service().setup(actor=admin, practice_name="Outro", idempotency_key="other")
        with pytest.raises(InvalidInput):
            service().setup(actor=admin, practice_name="X", timezone="Mars/Olympus", idempotency_key="tz")
    with clinic.as_user(clinic.a.reception) as actor:
        assert service().practice(actor=actor).name == "Consultório Central"
        assert not service().practice(actor=actor).writable
    with clinic.as_user(clinic.b.admin, clinic.org_b) as actor, pytest.raises(NotFound):
        service().practice(actor=actor)


def test_professionals_rooms_and_types(ready, subtests):
    with as_admin(ready) as admin:
        doctor = service().register_professional(
            actor=admin,
            display_name="Dra. Ana",
            council="crm",
            council_number="123456",
            council_state="SP",
            membership_user_id=ready.a.doctor.pk,
            idempotency_key="ana",
        )
        assert doctor.council_label == "CRM-SP 123456"
        again = service().register_professional(actor=admin, display_name="Dra. Ana", idempotency_key="ana")
        assert again.sysid == doctor.sysid
        with pytest.raises(Conflict):
            service().register_professional(actor=admin, display_name="Outra", membership_user_id=ready.a.doctor.pk)
        with pytest.raises(InvalidInput):
            service().register_professional(actor=admin, display_name="Fora", membership_user_id=ready.b.doctor.pk)
        room = service().add_room(actor=admin, name="Sala 1")
        consult = service().add_appointment_type(actor=admin, code="consulta", name="Consulta", duration_minutes=30)
        with pytest.raises(Conflict):
            service().add_appointment_type(actor=admin, code="consulta", name="Repetido")
        with pytest.raises(InvalidInput):
            service().add_appointment_type(actor=admin, code="Bad Code", name="X")
    with subtests.test("the kind says how it is paid for"), as_admin(ready) as admin:
        assert consult.payment_kind == "private"
        insured = service().add_appointment_type(actor=admin, code="unimed", name="Unimed", payment_kind="insurance")
        assert insured.payment_kind == "insurance"
        changed = service().update_appointment_type(
            actor=admin,
            type_id=insured.sysid,
            changes=(("payment_kind", "courtesy"), ("duration_minutes", 20)),
            expected_revision=insured.revision,
        )
        assert (changed.payment_kind, changed.duration_minutes) == ("courtesy", 20)
        with pytest.raises(InvalidInput) as error:
            service().add_appointment_type(actor=admin, code="vale", name="Vale", payment_kind="voucher")
        assert set(error.value.errors) == {"payment_kind"}
        with pytest.raises(InvalidInput) as error:
            service().update_appointment_type(
                actor=admin, type_id=insured.sysid, changes=(("payment_kind", ""),), expected_revision=changed.revision
            )
        assert set(error.value.errors) == {"payment_kind"}
        assert [row.payment_kind for row in service().appointment_types(actor=admin)] == ["private", "courtesy"]
    with subtests.test("my professional"), ready.as_user(ready.a.doctor) as actor:
        assert service().my_professional(actor=actor).sysid == doctor.sysid
    with subtests.test("reception reads and does not change"), ready.as_user(ready.a.reception) as actor:
        assert [row.sysid for row in service().professionals(actor=actor)] == [doctor.sysid]
        assert [row.sysid for row in service().rooms(actor=actor)] == [room.sysid]
        assert [row.code for row in service().appointment_types(actor=actor)] == ["consulta", "unimed"]
        assert service().my_professional(actor=actor) is None
        with pytest.raises(Forbidden):
            service().add_room(actor=actor, name="Sala 2")
        with pytest.raises(Forbidden):
            service().update_appointment_type(
                actor=actor, type_id=consult.sysid, changes=(("name", "X"),), expected_revision=1
            )
        with pytest.raises(Forbidden):
            service().update_appointment_type(
                actor=actor, type_id=consult.sysid, changes=(("payment_kind", "insurance"),), expected_revision=1
            )
    with subtests.test("CAS"):

        def rename(name):
            def call():
                with as_admin(ready) as admin:
                    return service().update_room(
                        actor=admin, room_id=room.sysid, changes=(("name", name),), expected_revision=1
                    )

            return call

        assert assert_cas_conflict(rename("Sala A"), rename("Sala B")).name == "Sala A"
    with subtests.test("deactivate"), as_admin(ready) as admin:
        service().set_professional_active(actor=admin, professional_id=doctor.sysid, active=False, expected_revision=1)
        assert service().professionals(actor=admin) == ()
        assert len(service().professionals(actor=admin, active_only=False)) == 1
    with subtests.test("audit redacts the professional"), as_admin(ready) as admin:
        from skeleton.service_api.audit import AuditService

        entries = AuditService().history(actor=admin, table_key="med_scheduling.professional", record_id=doctor.sysid)
        values = {str(change.new) for entry in entries.items for change in entry.changes}
        assert "Dra. Ana" not in values and "123456" not in values
