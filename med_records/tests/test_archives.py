"""Clinical archives: setup by the administrator, shared or per professional, and who reads what."""

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.service_api import assert_service_contract

from ..service_api import RecordsService
from .helpers import new_patient, prepare, register_doctor, setup_patients, setup_practice


def service():
    return RecordsService()


def test_service_contract():
    assert_service_contract(RecordsService)


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def test_setup_is_idempotent_and_only_for_the_administrator(ready):
    with ready.as_user(ready.a.admin) as admin:
        again = service().setup(
            actor=admin, member_group_ids=(ready.a.groups["professionals"],), idempotency_key="records"
        )
        assert len(again) == 1 and again[0].is_default
        with pytest.raises(Conflict) as error:
            service().setup(actor=admin, idempotency_key="other")
        assert error.value.code == "already_set_up"
        with pytest.raises(InvalidInput):
            service().setup(actor=admin, mode="nope", idempotency_key="x")
    with ready.as_user(ready.a.reception) as actor, pytest.raises(Forbidden):
        service().setup(actor=actor, idempotency_key="records")


def test_reception_reads_no_archive(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.doctor) as doctor:
        chart = service().open_chart(actor=doctor, patient_id=patient.sysid)
        assert [item.name for item in service().archives(actor=doctor)] == ["Prontuário da clínica"]
    with ready.as_user(ready.a.reception) as actor:
        assert service().archives(actor=actor) == ()
        assert service().charts_for_patient(actor=actor, patient_id=patient.sysid) == ()
        with pytest.raises(NotFound):
            service().chart(actor=actor, chart_id=chart.sysid)
        with pytest.raises(Forbidden):
            service().open_chart(actor=actor, patient_id=patient.sysid)


def test_personal_archives_do_not_share_charts(clinic):
    setup_patients(clinic)
    setup_practice(clinic)
    register_doctor(clinic)
    with clinic.as_user(clinic.a.admin) as admin:
        from applications.med_scheduling.service_api import SchedulingService

        SchedulingService().register_professional(
            actor=admin, display_name="Dr. Bruno", membership_user_id=clinic.a.finance.pk, idempotency_key="bruno"
        )
        archives = service().setup(actor=admin, mode="per_professional", idempotency_key="records")
    assert sorted(item.kind for item in archives) == ["personal", "personal"]
    patient = new_patient(clinic)
    with clinic.as_user(clinic.a.doctor) as doctor:
        mine = service().open_chart(actor=doctor, patient_id=patient.sysid)
        assert [item.name for item in service().archives(actor=doctor)] == ["Dra. Ana"]
    with clinic.as_user(clinic.a.finance) as other:
        theirs = service().open_chart(actor=other, patient_id=patient.sysid)
        assert theirs.sysid != mine.sysid
        assert [chart.sysid for chart in service().charts_for_patient(actor=other, patient_id=patient.sysid)] == [
            theirs.sysid
        ]
        with pytest.raises(NotFound):
            service().chart(actor=other, chart_id=mine.sysid)


def test_create_archive_for_a_group(ready):
    with ready.as_user(ready.a.admin) as admin:
        extra = service().create_archive(
            actor=admin, name="Psicologia", writer_group_ids=(ready.a.groups["finance"],), idempotency_key="psi"
        )
        assert service().create_archive(actor=admin, name="Psicologia", idempotency_key="psi").sysid == extra.sysid
    patient = new_patient(ready)
    with ready.as_user(ready.a.finance) as actor:
        chart = service().open_chart(actor=actor, patient_id=patient.sysid)
        assert chart.archive_id == extra.sysid
    with ready.as_user(ready.a.doctor) as doctor:
        assert service().charts_for_patient(actor=doctor, patient_id=patient.sysid) == ()
        with pytest.raises(InvalidInput):
            service().open_chart(actor=doctor, patient_id=patient.sysid, archive_id="bad")
