"""The plan limits: the professionals meter limits the agenda, the patients meter only measures."""

import pytest

from applications.med_patients.service_api import PatientService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict
from skeleton.service_api.billing import BillingService

from .journey import new_patient, set_up


@pytest.fixture
def ready(clinic):
    set_up(clinic, clinic.a)
    set_up(clinic, clinic.b)
    return clinic


def counters():
    from applications.med_patients.registration import count_active_patients
    from applications.med_scheduling.registration import count_active_professionals

    return count_active_professionals, count_active_patients


def test_without_billing_there_is_no_limit(ready):
    with ready.as_user(ready.a.admin) as admin:
        for number in range(3):
            SchedulingService().register_professional(
                actor=admin, display_name=f"Profissional {number}", idempotency_key=f"extra-{number}"
            )
        assert len(SchedulingService().professionals(actor=admin)) == 4


def test_above_the_limit_nothing_is_created(ready, monkeypatch):
    seen = []

    def over_the_limit(self, *, actor, metric, increment=1):
        seen.append((metric, increment))
        raise Conflict("quota_exceeded")

    monkeypatch.setattr(BillingService, "check_quota", over_the_limit)
    with ready.as_user(ready.a.admin) as admin:
        with pytest.raises(Conflict) as error:
            SchedulingService().register_professional(actor=admin, display_name="Excedente", idempotency_key="x")
        assert error.value.code == "quota_exceeded"
        assert [item.display_name for item in SchedulingService().professionals(actor=admin)] == ["Dra. Ana"]
        (doctor,) = SchedulingService().professionals(actor=admin)
        off = SchedulingService().set_professional_active(
            actor=admin, professional_id=doctor.sysid, active=False, expected_revision=doctor.revision
        )
        with pytest.raises(Conflict):
            SchedulingService().set_professional_active(
                actor=admin, professional_id=doctor.sysid, active=True, expected_revision=off.revision
            )
    assert seen == [("med_scheduling.active_professionals", 1)] * 2


def test_counters_count_live_active_rows_of_the_organization(ready):
    professionals, patients = counters()
    first = new_patient(ready, ready.a, full_name="Ativo")
    second = new_patient(ready, ready.a, full_name="Outro")
    new_patient(ready, ready.b, full_name="Da outra organização")
    with ready.as_user(ready.a.reception) as actor:
        current = PatientService().get(actor=actor, patient_id=second.sysid)
        PatientService().delete(actor=actor, patient_id=second.sysid, expected_revision=current.revision)
        assert patients(ready.org_a.pk) == 1
        assert professionals(ready.org_a.pk) == 1
    with ready.as_user(ready.a.admin) as admin:
        (doctor,) = SchedulingService().professionals(actor=admin)
        SchedulingService().set_professional_active(
            actor=admin, professional_id=doctor.sysid, active=False, expected_revision=doctor.revision
        )
        assert professionals(ready.org_a.pk) == 0
    assert first.code
