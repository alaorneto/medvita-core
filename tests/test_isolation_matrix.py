"""Who reads and writes what across the four apps, organization B seeing nothing of A, apps turned off."""

import pytest

from applications.med_finance.service_api import ChargeItemInput, FinanceService
from applications.med_patients.service_api import PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict, Forbidden, NotFound, Unavailable

from .journey import monday_at, new_patient, set_up


class Ready:
    """The clinic fixture plus the identifiers prepared for the test, forwarding everything else."""

    def __init__(self, clinic, ids):
        self._clinic = clinic
        self.ids = ids

    def __getattr__(self, name):
        return getattr(self._clinic, name)


@pytest.fixture
def ready(clinic):
    a = set_up(clinic, clinic.a)
    set_up(clinic, clinic.b)
    patient = new_patient(clinic, clinic.a, full_name="Paciente da Matriz")
    with clinic.as_user(clinic.a.reception) as actor:
        appointment = SchedulingService().book(
            actor=actor,
            schedule_id=a.schedule.sysid,
            patient_id=patient.sysid,
            appointment_type_id=a.kind.sysid,
            starts_at=monday_at(9),
            idempotency_key="book",
        )
        charge = (
            FinanceService()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="charge"
            )
            .charge
        )
    with clinic.as_user(clinic.a.doctor) as doctor:
        chart = RecordsService().open_chart(actor=doctor, patient_id=patient.sysid)
        encounter = RecordsService().start_encounter(actor=doctor, chart_id=chart.sysid, idempotency_key="e")
    ids = {
        "patient": patient.sysid,
        "appointment": appointment.sysid,
        "charge": charge.sysid,
        "chart": chart.sysid,
        "encounter": encounter.header.sysid,
    }
    return Ready(clinic, ids)


READS = {
    "patient": lambda actor, ids: PatientService().get(actor=actor, patient_id=ids["patient"]),
    "appointment": lambda actor, ids: SchedulingService().appointment(actor=actor, appointment_id=ids["appointment"]),
    "chart": lambda actor, ids: RecordsService().chart(actor=actor, chart_id=ids["chart"]),
    "encounter": lambda actor, ids: RecordsService().encounter(actor=actor, encounter_id=ids["encounter"]),
    "charge": lambda actor, ids: FinanceService().charge(actor=actor, charge_id=ids["charge"]),
}
# Who of organization A reads each record (docs/access-model.md).
EXPECTED = {
    "reception": {"patient", "appointment", "charge"},
    "doctor": {"patient", "appointment", "chart", "encounter"},
    "finance": {"patient", "charge"},
    "admin": {"patient", "appointment", "chart", "encounter", "charge"},
}


def test_who_reads_what(ready, subtests):
    for role, readable in EXPECTED.items():
        user = getattr(ready.a, role)
        for name, read in READS.items():
            with subtests.test(role=role, record=name), ready.as_user(user) as actor:
                if name in readable:
                    read(actor, ready.ids)
                else:
                    with pytest.raises(NotFound):
                        read(actor, ready.ids)


def test_organization_b_sees_nothing_of_a(ready, subtests):
    for role in ("reception", "doctor", "finance", "admin"):
        for name, read in READS.items():
            with subtests.test(role=role, record=name), ready.as_user(getattr(ready.b, role), ready.org_b) as actor:
                with pytest.raises(NotFound):
                    read(actor, ready.ids)


def test_writes_follow_the_containers(ready):
    with ready.as_user(ready.a.reception) as actor, pytest.raises(Forbidden):
        RecordsService().open_chart(actor=actor, patient_id=ready.ids["patient"])
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(NotFound):
            FinanceService().open_session(actor=doctor, idempotency_key="x")
    with ready.as_user(ready.a.finance) as actor:
        current = SchedulingService().schedules(actor=actor)
        assert current == ()
    with ready.as_user(ready.a.reception) as actor:
        FinanceService().open_session(actor=actor, idempotency_key="open")
    with ready.as_user(ready.a.finance) as actor:
        session = FinanceService().current_session(actor=actor)
        with pytest.raises(Forbidden):
            FinanceService().close_session(
                actor=actor, session_id=session.sysid, counted_amount=0, expected_revision=session.revision
            )


def test_turning_apps_off(ready, subtests):
    with ready.app_disabled("med_finance"), ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Unavailable):
            FinanceService().charges(actor=actor)
        actions = SchedulingService().appointment_actions(actor=actor, appointment_id=ready.ids["appointment"])
        assert "med_finance.collect" not in [item.code for item in actions]
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=ready.ids["patient"])]
        assert "med_finance.account" not in tabs
        assert SchedulingService().appointment(actor=actor, appointment_id=ready.ids["appointment"])
    with ready.app_disabled("med_records"), ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Unavailable):
            RecordsService().chart(actor=doctor, chart_id=ready.ids["chart"])
        PatientService().get(actor=doctor, patient_id=ready.ids["patient"])


def test_a_patient_with_records_is_not_deleted(ready):
    with ready.as_user(ready.a.reception) as actor:
        patient = PatientService().get(actor=actor, patient_id=ready.ids["patient"])
        with pytest.raises(Conflict) as error:
            PatientService().delete(actor=actor, patient_id=patient.sysid, expected_revision=patient.revision)
    assert error.value.code in ("live_references", "retention")
