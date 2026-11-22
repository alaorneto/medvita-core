"""The whole day of a clinic through the public services, with the privacy sweep afterwards.

Reception registers and books, the doctor attends, signs and issues a certificate, the reception
receives and the finance team closes the desk. Then no personal or clinical data of the scenario
may appear in events, the calendar, the ledger, the audit (it must be redacted) or the logs.
"""

import logging
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from applications.med_finance.service_api import FinanceService
from applications.med_patients.service_api import PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import AvailabilityRuleInput, SchedulingService
from skeleton.contrib.calendar.service_api import CalendarService
from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api import InvalidInput
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


def test_a_morning_by_order_of_arrival(ready):
    """A Monday seen in the order of arrival: no time is booked, the legal priority goes first, the
    doctor attends from the queue, the private appointment is charged and the insurance one is not.
    Nothing of the patients, nor the priority, leaves in the events or in the calendar."""
    a = ready.a
    clinic = ready
    scheduling = SchedulingService()
    monday = monday_at(8).date()
    walker = new_patient(clinic, a, full_name=NAME, cpf=CPF, phone=PHONE)
    elder = new_patient(clinic, a, full_name="Olga Idosa Sigilosa")
    with clinic.as_user(a.admin) as admin:
        insured = scheduling.add_appointment_type(
            actor=admin, code="unimed", name="Unimed", payment_kind="insurance", idempotency_key="unimed"
        )
    with capture_events() as events:
        with clinic.as_user(a.reception) as actor:
            (schedule,) = scheduling.schedules(actor=actor)
            private = next(kind for kind in scheduling.appointment_types(actor=actor) if kind.code == "consulta")
            scheduling.set_availability(
                actor=actor,
                schedule_id=schedule.sysid,
                rules=(AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1), mode="walk_in", capacity=10),),
                expected_revision=schedule.revision,
            )
            booked = [
                scheduling.book(
                    actor=actor,
                    schedule_id=schedule.sysid,
                    patient_id=patient.sysid,
                    appointment_type_id=kind.sysid,
                    starts_at=monday_at(9),
                    mode="walk_in",
                    idempotency_key=f"walk-{kind.code}",
                )
                for patient, kind in ((walker, private), (elder, insured))
            ]
            # Neither has a time: both carry the bounds of the period, and the payment of the kind.
            assert {(row.mode, row.starts_at, row.ends_at) for row in booked} == {
                ("walk_in", monday_at(8), monday_at(12))
            }
            assert [row.payment_kind for row in booked] == ["private", "insurance"]
            first = scheduling.check_in(
                actor=actor, appointment_id=booked[0].sysid, expected_revision=booked[0].revision
            )
            second = scheduling.check_in(
                actor=actor, appointment_id=booked[1].sysid, expected_revision=booked[1].revision, priority=True
            )
            assert (first.arrival_number, second.arrival_number) == (1, 2)
            (session,) = scheduling.queue(actor=actor, schedule_id=schedule.sysid, date=monday)
            assert (session.capacity, session.taken) == (10, 2)
            assert [(entry.appointment.sysid, entry.is_priority) for entry in session.waiting] == [
                (second.sysid, True),
                (first.sysid, False),
            ]
        records = RecordsService()
        with clinic.as_user(a.doctor) as doctor:
            for appointment, patient in ((second, elder), (first, walker)):
                chart = records.open_chart(actor=doctor, patient_id=patient.sysid)
                draft = records.start_encounter(
                    actor=doctor,
                    chart_id=chart.sysid,
                    appointment_id=appointment.sysid,
                    idempotency_key=f"attend-{appointment.code}",
                )
                draft = records.save_section(
                    actor=doctor,
                    encounter_id=draft.header.sysid,
                    section_type="med_records.anamnesis",
                    data=(("chief_complaint", COMPLAINT),),
                    expected_revision=draft.header.revision,
                )
                signed = records.sign_encounter(
                    actor=doctor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
                )
                assert signed.appointment_completed
        finance = FinanceService()
        with clinic.as_user(a.reception) as actor:
            (session,) = scheduling.queue(actor=actor, schedule_id=schedule.sysid, date=monday)
            assert not session.waiting and {entry.appointment.status for entry in session.finished} == {"completed"}
            charge = finance.charge_for_appointment(
                actor=actor, appointment_id=first.sysid, idempotency_key="collect-private"
            ).charge
            assert charge.total == 25000
            with pytest.raises(InvalidInput) as refused:
                finance.charge_for_appointment(
                    actor=actor, appointment_id=second.sysid, idempotency_key="collect-insurance"
                )
            assert set(refused.value.errors) == {"appointment_id"}

    secrets = (NAME, CPF, PHONE, COMPLAINT, "Olga Idosa Sigilosa")
    payloads = repr([event.data for event in events])
    assert not [secret for secret in secrets if secret in payloads] and "priority" not in payloads
    arrivals = [event.data for event in events if event.event_type == "med_scheduling.appointment_arrived"]
    assert len(arrivals) == 2 and {data["mode"] for data in arrivals} == {"walk_in"}
    # The reception reads the schedule, and so its calendar; whoever does not sees "Ocupado".
    with clinic.as_user(a.reception) as reader:
        calendar = CalendarService()
        # One event for the session, counting the patients; none for each appointment.
        event = calendar.managed_event(
            actor=reader, source_app="med_scheduling", source_key=f"session:{schedule.sysid}:{monday:%Y%m%d}:480"
        )
        assert event is not None and event.title == "Ordem de chegada · 2 pacientes"
        shown = repr(event)
        assert not [secret for secret in (*secrets, first.code, second.code) if secret in shown]
        for row in (first, second):
            assert calendar.managed_event(actor=reader, source_app="med_scheduling", source_key=str(row.sysid)) is None


def test_the_calendar_file_of_a_schedule_names_no_patient(ready):
    """What leaves to a calendar client (the phone's): the kind and the code of an appointment, how
    many patients a session by order of arrival has, and the blocks. Never a patient, a note or a
    priority, whoever reads; and only the owner of the schedule and who booked read even that much."""
    a = ready.a
    clinic = ready
    scheduling = SchedulingService()
    walker = new_patient(clinic, a, full_name=NAME, cpf=CPF, phone=PHONE)
    elder = new_patient(clinic, a, full_name="Olga Idosa Sigilosa")
    with clinic.as_user(a.reception) as actor:
        (schedule,) = scheduling.schedules(actor=actor)
        (kind,) = scheduling.appointment_types(actor=actor)
        scheduling.set_availability(
            actor=actor,
            schedule_id=schedule.sysid,
            rules=(
                AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),
                AvailabilityRuleInput(0, 14 * 60, 18 * 60, date(2026, 1, 1), mode="walk_in", capacity=10),
            ),
            expected_revision=schedule.revision,
        )
        timed = scheduling.book(
            actor=actor,
            schedule_id=schedule.sysid,
            patient_id=walker.sysid,
            appointment_type_id=kind.sysid,
            starts_at=monday_at(9),
            notes=COMPLAINT,
            idempotency_key="timed",
        )
        arrivals = [
            scheduling.book(
                actor=actor,
                schedule_id=schedule.sysid,
                patient_id=patient.sysid,
                appointment_type_id=kind.sysid,
                starts_at=monday_at(14),
                mode="walk_in",
                notes=COMPLAINT,
                idempotency_key=f"arrival-{index}",
            )
            for index, patient in enumerate((walker, elder))
        ]
        scheduling.check_in(
            actor=actor, appointment_id=arrivals[1].sysid, expected_revision=arrivals[1].revision, priority=True
        )
        scheduling.add_block(
            actor=actor,
            schedule_id=schedule.sysid,
            starts_at=monday_at(11),
            ends_at=monday_at(12),
            reason="other",
            note=ALLERGY,
            idempotency_key="block",
        )
    secrets = (NAME, CPF, PHONE, COMPLAINT, ALLERGY, "Olga", str(walker.sysid), str(elder.sysid), "priorit")
    organization = a.organization.pk
    download = reverse("skeleton_calendar:calendar-ics", args=(organization, schedule.calendar_id))
    link_page = reverse("skeleton_calendar:calendar-link", args=(organization, schedule.calendar_id))

    def files(user):
        """The file downloaded with the session and the one a calendar client gets through the person's link."""
        client = Client()
        client.force_login(user)
        downloaded = client.get(download)
        issued = client.post(link_page)
        assert (downloaded.status_code, issued.status_code) == (200, 201)
        subscribed = Client().get(issued.context["url"])
        assert subscribed.status_code == 200
        return downloaded.content.decode(), subscribed.content.decode()

    # The doctor owns the schedule and the reception booked: both read the titles the app wrote.
    for user in (a.doctor, a.reception):
        for body in files(user):
            assert f"Consulta · {timed.code}" in body
            assert "Ordem de chegada · 2 pacientes" in body and "Bloqueio" in body
            assert not [secret for secret in secrets if secret in body]
            assert not [row.code for row in arrivals if row.code in body]
    # Anyone else who reads the schedule gets the hours as busy, and nothing more.
    with clinic.as_user(a.admin) as admin:
        current = scheduling.schedule(actor=admin, schedule_id=schedule.sysid)
        scheduling.set_schedule_access(
            actor=admin,
            schedule_id=schedule.sysid,
            writer_group_ids=(a.groups["reception"],),
            reader_group_ids=(a.groups["finance"],),
            writer_user_ids=(a.doctor.pk,),
            expected_revision=current.revision,
        )
    for body in files(a.finance):
        assert "Ocupado" in body and "Consulta" not in body and "Ordem de chegada" not in body
        assert timed.code not in body and not [secret for secret in secrets if secret in body]
    # A person of organization B has no file of A.
    other = Client()
    other.force_login(ready.b.admin)
    assert other.get(download).status_code == 404
    assert (
        other.get(
            reverse("skeleton_calendar:calendar-ics", args=(ready.b.organization.pk, schedule.calendar_id))
        ).status_code
        == 404
    )
