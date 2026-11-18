"""The whole day of a clinic through the public services, with the privacy sweep afterwards.

Reception registers and books, the doctor attends, signs and issues a certificate, the reception
receives and the finance team closes the desk. Then no personal or clinical data of the scenario
may appear in events, the calendar, the ledger, the audit (it must be redacted) or the logs.
"""

import logging

import pytest

from applications.med_finance.service_api import FinanceService
from applications.med_patients.service_api import PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api.audit import AuditService
from skeleton.testing.events import capture_events

from .journey import monday_at, new_patient, set_up

NAME = "Joana Jornada Sigilosa"
CPF = "11144477735"
PHONE = "11987654321"
COMPLAINT = "dor lombar irradiada"
ALLERGY = "dipirona sódica"


@pytest.fixture
def ready(clinic):
    set_up(clinic, clinic.a)
    set_up(clinic, clinic.b)
    return clinic


def test_the_day_of_the_clinic(ready, caplog):
    a = ready.a
    clinic = ready
    caplog.set_level(logging.INFO)
    with capture_events() as events:
        patient = new_patient(clinic, a, full_name=NAME, cpf=CPF, phone=PHONE)
        scheduling = SchedulingService()
        with clinic.as_user(a.reception) as actor:
            (schedule,) = scheduling.schedules(actor=actor)
            (kind,) = scheduling.appointment_types(actor=actor)
            booked = scheduling.book(
                actor=actor,
                schedule_id=schedule.sysid,
                patient_id=patient.sysid,
                appointment_type_id=kind.sysid,
                starts_at=monday_at(9),
                notes=COMPLAINT,
                idempotency_key="book",
            )
            arrived = scheduling.check_in(actor=actor, appointment_id=booked.sysid, expected_revision=booked.revision)
        records = RecordsService()
        with clinic.as_user(a.doctor) as doctor:
            chart = records.open_chart(actor=doctor, patient_id=patient.sysid)
            draft = records.start_encounter(
                actor=doctor, chart_id=chart.sysid, appointment_id=arrived.sysid, idempotency_key="attend"
            )
            draft = records.save_section(
                actor=doctor,
                encounter_id=draft.header.sysid,
                section_type="med_records.anamnesis",
                data=(("chief_complaint", COMPLAINT),),
                expected_revision=draft.header.revision,
            )
            records.add_allergy(actor=doctor, chart_id=chart.sysid, substance=ALLERGY, idempotency_key="allergy")
            signed = records.sign_encounter(
                actor=doctor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
            )
            assert signed.header.signed and signed.appointment_completed
            certificate = records.draft_document(
                actor=doctor, chart_id=chart.sysid, kind="med_records.certificate", idempotency_key="cert"
            )
            issued = records.issue_document(
                actor=doctor, document_id=certificate.header.sysid, expected_revision=certificate.header.revision
            )
            assert NAME in issued.body
        finance = FinanceService()
        with clinic.as_user(a.reception) as actor:
            assert scheduling.appointment(actor=actor, appointment_id=booked.sysid).appointment.status == "completed"
            session = finance.open_session(actor=actor, opening_amount=5000, idempotency_key="open")
            charge = finance.charge_for_appointment(
                actor=actor, appointment_id=booked.sysid, idempotency_key="collect"
            ).charge
            finance.register_payment(
                actor=actor,
                charge_id=charge.sysid,
                method="pix",
                amount=10000,
                expected_revision=charge.revision,
                idempotency_key="pix",
            )
            current = finance.charge(actor=actor, charge_id=charge.sysid).charge
            finance.register_payment(
                actor=actor,
                charge_id=charge.sysid,
                method="cash",
                amount=15000,
                expected_revision=current.revision,
                idempotency_key="cash",
            )
            assert finance.charge(actor=actor, charge_id=charge.sysid).charge.status == "paid"
            assert len(finance.receipts(actor=actor, charge_id=charge.sysid).items) == 2
        with clinic.as_user(a.finance) as actor:
            current = finance.current_session(actor=actor)
        with clinic.as_user(a.reception) as actor:
            closed = finance.close_session(
                actor=actor, session_id=session.sysid, counted_amount=20000, expected_revision=current.revision
            )
            assert closed.difference == 0
            timeline = [item.title for item in PatientService().timeline(actor=actor, patient_id=patient.sysid).items]
        assert "Conta emitida" in timeline and "Consulta realizada" in timeline
    secrets = (NAME, CPF, PHONE, COMPLAINT, ALLERGY)

    # Domain events: identifiers, codes and statuses only.
    assert {event.event_type for event in events} >= {
        "med_patients.patient_created",
        "med_scheduling.appointment_booked",
        "med_scheduling.appointment_completed",
        "med_records.encounter_signed",
        "med_records.document_issued",
        "med_finance.charge_confirmed",
        "med_finance.charge_paid",
        "med_finance.receipt_issued",
    }
    payloads = repr([event.data for event in events])
    assert not [secret for secret in secrets if secret in payloads]

    with clinic.as_user(a.admin) as admin:
        # Calendar: kind and code only.
        event = CalendarService().managed_event(actor=admin, source_app="med_scheduling", source_key=str(booked.sysid))
        assert event is None or not [secret for secret in secrets if secret in repr(event)]
        # Ledger: the patient only as party_ref.
        (title,) = LedgerService().titles_for_source(
            actor=admin, table_key="med_finance.charge", record_id=charge.sysid
        )
        assert title.party_ref == str(patient.sysid) and not [secret for secret in secrets if secret in repr(title)]
        # Audit: personal and clinical fields redacted.
        audited = repr(
            [
                AuditService().history(actor=admin, table_key=table, record_id=record_id).items
                for table, record_id in (
                    ("med_patients.patient", patient.sysid),
                    ("med_scheduling.appointment", booked.sysid),
                    ("med_records.encountersection", signed.sections[0].sysid),
                )
            ]
        )
        assert not [secret for secret in secrets if secret in audited] and "REDACTED" in audited
    logged = caplog.text + repr([record.__dict__ for record in caplog.records])
    assert not [secret for secret in secrets if secret in logged]
