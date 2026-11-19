"""Integrity between the apps: a patient with an appointment cannot be deleted."""

import pytest

from applications.med_patients.service_api import PatientService
from applications.med_scheduling.tests.booking import book, prepare
from skeleton.service_api import Conflict


def test_patient_with_an_appointment_is_not_deleted(clinic):
    ready = prepare(clinic)
    book(ready, 9)
    with ready.as_user(ready.a.reception) as actor:
        patient = PatientService().get(actor=actor, patient_id=ready.patient.sysid)
        with pytest.raises(Conflict) as error:
            PatientService().delete(actor=actor, patient_id=patient.sysid, expected_revision=patient.revision)
    assert error.value.code == "live_references"
