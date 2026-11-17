"""The finance app on the agenda and on the patient page: Receber, tab, timeline, report, retention."""

import pytest

from applications.med_patients.service_api import PatientService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict, InvalidInput

from ..service_api import FinanceService
from .helpers import add_price, book, new_patient, prepare


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    return clinic


def test_charge_for_a_private_appointment(ready):
    patient = new_patient(ready)
    appointment = book(ready, patient)
    with ready.as_user(ready.a.reception) as actor:
        codes = [
            item.code for item in SchedulingService().appointment_actions(actor=actor, appointment_id=appointment.sysid)
        ]
        assert "med_finance.collect" in codes
        detail = service().charge_for_appointment(actor=actor, appointment_id=appointment.sysid, idempotency_key="a")
        again = service().charge_for_appointment(actor=actor, appointment_id=appointment.sysid, idempotency_key="b")
    charge = detail.charge
    assert again.charge.sysid == charge.sysid
    assert (charge.origin_app, charge.origin_key, charge.appointment_id) == (
        "med_scheduling",
        str(appointment.sysid),
        appointment.sysid,
    )
    assert charge.total == 25000 and charge.status == "open"


def test_insurance_appointment_has_no_charge(ready):
    patient = new_patient(ready)
    appointment = book(ready, patient, payment_kind="insurance")
    with ready.as_user(ready.a.reception) as actor, pytest.raises(InvalidInput):
        service().charge_for_appointment(actor=actor, appointment_id=appointment.sysid, idempotency_key="a")


def test_patient_page_and_retention(ready):
    patient = new_patient(ready)
    appointment = book(ready, patient)
    with ready.as_user(ready.a.reception) as actor:
        service().charge_for_appointment(actor=actor, appointment_id=appointment.sysid, idempotency_key="a")
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=patient.sysid)]
        timeline = [entry.title for entry in PatientService().timeline(actor=actor, patient_id=patient.sysid).items]
    assert "med_finance.account" in tabs and "Conta emitida" in timeline
    with ready.as_user(ready.a.doctor) as doctor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=doctor, patient_id=patient.sysid)]
    assert "med_finance.account" not in tabs
    with ready.as_user(ready.a.admin) as admin:
        current = PatientService().get(actor=admin, patient_id=patient.sysid)
        report = PatientService().data_report(actor=admin, patient_id=patient.sysid)
        with pytest.raises(Conflict) as error:
            PatientService().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=current.revision)
    assert "5 anos" in str(error.value.detail)
    assert "250.00" in repr(report)
