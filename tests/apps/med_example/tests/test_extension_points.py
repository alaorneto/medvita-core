"""Every extension point of the four apps, used by an app that changes none of them."""

import pytest

from applications.med_finance.service_api import FinanceService
from applications.med_patients.service_api import PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict
from skeleton.service_api.records import RecordSealService
from skeleton.testing.applications import activate_app, open_app
from skeleton.testing.jobs import run_pending_jobs
from tests.journey import monday_at, new_patient, set_up

from ..service_api import ExampleService


@pytest.fixture
def ready(clinic):
    prepared = set_up(clinic, clinic.a)
    open_app("med_example")
    activate_app("med_example", clinic.org_a.pk)
    with clinic.as_user(clinic.a.admin) as admin:
        ExampleService().setup(
            actor=admin,
            writer_group_ids=(clinic.a.groups["reception"], clinic.a.groups["professionals"]),
            idempotency_key="board",
        )
    patient = new_patient(clinic, clinic.a, full_name="Paciente do Exemplo")
    with clinic.as_user(clinic.a.reception) as actor:
        booked = SchedulingService().book(
            actor=actor,
            schedule_id=prepared.schedule.sysid,
            patient_id=patient.sysid,
            appointment_type_id=prepared.kind.sysid,
            starts_at=monday_at(9),
            idempotency_key="book",
        )
        arrived = SchedulingService().check_in(
            actor=actor, appointment_id=booked.sysid, expected_revision=booked.revision
        )
    return clinic, patient, arrived


def test_patient_page_registries(ready):
    clinic, patient, _appointment = ready
    with clinic.as_user(clinic.a.reception) as actor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=patient.sysid)]
        purposes = [item.code for item in PatientService().consent_purposes(actor=actor)]
        ExampleService().add_note(actor=actor, patient_id=patient.sysid, text="Primeira nota")
        timeline = [entry.source for entry in PatientService().timeline(actor=actor, patient_id=patient.sysid).items]
    assert "med_example.notes" in tabs and "med_example.reminders" in purposes
    assert "med_example.notes" in timeline
    with clinic.as_user(clinic.a.admin) as admin:
        steps = [step.code for step in PatientService().setup_steps(actor=admin)]
        report = PatientService().data_report(actor=admin, patient_id=patient.sysid)
    assert "med_example.board" in steps and "Notas de exemplo" in repr(report)
    with clinic.app_disabled("med_example"), clinic.as_user(clinic.a.reception) as actor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=patient.sysid)]
        assert "med_example.notes" not in tabs


def test_retention_guard(ready):
    clinic, patient, _appointment = ready
    with clinic.as_user(clinic.a.reception) as actor:
        ExampleService().add_note(actor=actor, patient_id=patient.sysid, text="Guardar", keep=True)
    with clinic.as_user(clinic.a.admin) as admin:
        current = PatientService().get(actor=admin, patient_id=patient.sysid)
        with pytest.raises(Conflict) as error:
            PatientService().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=current.revision)
    assert "Nota de exemplo" in str(error.value.detail)


def test_agenda_records_and_finance(ready):
    clinic, patient, appointment = ready
    with clinic.as_user(clinic.a.reception) as actor:
        actions = [
            item.code for item in SchedulingService().appointment_actions(actor=actor, appointment_id=appointment.sysid)
        ]
    assert "med_example.look" in actions
    records = RecordsService()
    with clinic.as_user(clinic.a.doctor) as doctor:
        chart = records.open_chart(actor=doctor, patient_id=patient.sysid)
        draft = records.start_encounter(
            actor=doctor, chart_id=chart.sysid, appointment_id=appointment.sysid, idempotency_key="e"
        )
        draft = records.save_section(
            actor=doctor,
            encounter_id=draft.header.sysid,
            section_type="med_example.eye_exam",
            data=(("visual_acuity", "20/20"),),
            expected_revision=draft.header.revision,
        )
        signed = records.sign_encounter(
            actor=doctor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
        )
        letter = records.draft_document(
            actor=doctor, chart_id=chart.sysid, kind="med_example.letter", idempotency_key="letter"
        )
        assert letter.body == "Para Paciente do Exemplo."
        assert records.verify_encounter(actor=doctor, encounter_id=signed.header.sysid).valid
        status = RecordSealService().status(
            actor=doctor, table_key="med_records.encounter", record_id=signed.header.sysid
        )
        assert status.digest == signed.header.seal_digest
    run_pending_jobs()
    with clinic.as_user(clinic.a.reception) as actor:
        sources = {note.source for note in ExampleService().notes(actor=actor, patient_id=patient.sysid)}
        charge_id = ExampleService().bill(
            actor=actor, patient_id=patient.sysid, amount=8000, key="laudo-1", idempotency_key="bill"
        )
        assert (
            ExampleService().bill(
                actor=actor, patient_id=patient.sysid, amount=8000, key="laudo-1", idempotency_key="again"
            )
            == charge_id
        )
        charge = FinanceService().charge(actor=actor, charge_id=charge_id).charge
    assert sources == {"med_scheduling.appointment_completed", "med_records.encounter_signed"}
    assert (charge.origin_app, charge.total) == ("med_example", 8000)


def _paid_charge(clinic, patient):
    """A charge of the example app, confirmed and paid in cash with its receipt."""
    finance = FinanceService()
    with clinic.as_user(clinic.a.reception) as actor:
        charge_id = ExampleService().bill(
            actor=actor, patient_id=patient.sysid, amount=8000, key="painel-1", idempotency_key="bill-panel"
        )
        charge = finance.charge(actor=actor, charge_id=charge_id).charge
        if charge.status == "draft":
            charge = finance.confirm_charge(actor=actor, charge_id=charge_id, expected_revision=charge.revision).charge
        if finance.current_session(actor=actor) is None:
            finance.open_session(actor=actor, idempotency_key="session-panel")
        payment = finance.register_payment(
            actor=actor,
            charge_id=charge_id,
            method="cash",
            amount=8000,
            expected_revision=charge.revision,
            idempotency_key="pay-panel",
        )
        receipt = finance.receipts(actor=actor, charge_id=charge_id).items[0]
    return charge_id, payment, receipt


def test_finance_panels(ready):
    from django.test import Client
    from django.urls import reverse

    clinic, patient, _appointment = ready
    charge_id, _payment, receipt = _paid_charge(clinic, patient)
    org = clinic.org_a.pk
    reception = Client()
    reception.force_login(clinic.a.reception)
    page = reception.get(reverse("med_finance:charge", args=(org, charge_id))).content.decode()
    assert "Nota de exemplo" in page and f"Situação de exemplo: Pendente · {charge_id}" in page
    page = reception.get(reverse("med_finance:receipt", args=(org, receipt.sysid))).content.decode()
    assert "Recibo de exemplo" in page and reverse("med_example:receipt_look", args=(org, receipt.sysid)) in page
    with clinic.as_user(clinic.a.reception) as actor:
        codes = [panel.code for panel in FinanceService().charge_panels(actor=actor, charge_id=charge_id)]
    assert codes == ["med_example.fiscal"]
    doctor = Client()
    doctor.force_login(clinic.a.doctor)
    assert doctor.get(reverse("med_finance:charge", args=(org, charge_id))).status_code == 404
    assert doctor.get(reverse("med_finance:receipt", args=(org, receipt.sysid))).status_code == 404
    with clinic.app_disabled("med_example"):
        page = reception.get(reverse("med_finance:charge", args=(org, charge_id))).content.decode()
        assert "Nota de exemplo" not in page
        page = reception.get(reverse("med_finance:receipt", args=(org, receipt.sysid))).content.decode()
        assert "Recibo de exemplo" not in page
