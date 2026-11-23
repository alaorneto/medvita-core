"""The data a fiscal document of a payment needs, read through the cash desk and never sent in an event."""

import pytest

from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.events import capture_events

from ..service_api import ChargeItemInput, FinanceService
from .helpers import add_price, book, new_patient, prepare

PATIENT_CPF = "11144477735"
DOCTOR_CPF = "52998224725"
PRACTICE_CNPJ = "11222333000181"


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    with clinic.as_user(clinic.a.admin) as admin:
        practice = SchedulingService().practice(actor=admin)
        SchedulingService().update_practice(
            actor=admin,
            changes=(("legal_name", "Clínica Central Ltda"), ("tax_id", PRACTICE_CNPJ)),
            expected_revision=practice.revision,
        )
    return clinic


def _paid(clinic, patient, *, issue_receipt=True, key="pay"):
    """The appointment's charge paid by Pix in an open session."""
    finance = FinanceService()
    appointment = book(clinic, patient)
    with clinic.as_user(clinic.a.reception) as actor:
        detail = finance.charge_for_appointment(actor=actor, appointment_id=appointment.sysid, idempotency_key="c")
        if finance.current_session(actor=actor) is None:
            finance.open_session(actor=actor, idempotency_key="session")
        with capture_events() as events:
            payment = finance.register_payment(
                actor=actor,
                charge_id=detail.charge.sysid,
                method="pix",
                amount=detail.charge.balance,
                expected_revision=detail.charge.revision,
                idempotency_key=key,
                issue_receipt=issue_receipt,
            )
    return appointment, detail.charge, payment, events


def test_a_pix_payment_returns_issuer_professional_payer_beneficiary_and_items(ready):
    patient = new_patient(ready, full_name="Maria Fiscal", cpf=PATIENT_CPF)
    appointment, charge, payment, events = _paid(ready, patient)
    with ready.as_user(ready.a.reception) as actor:
        data = FinanceService().fiscal_data(actor=actor, payment_id=payment.sysid)
    with ready.as_user(ready.a.finance) as actor:
        # Who reads the desk but not the schedule gets the payment without the appointment's professional.
        blind = FinanceService().fiscal_data(actor=actor, payment_id=payment.sysid)
    assert (blind.issuer_document, blind.professional_name, blind.payer_document) == (PRACTICE_CNPJ, "", PATIENT_CPF)
    assert (data.payment_id, data.charge_id, data.appointment_id) == (payment.sysid, charge.sysid, appointment.sysid)
    assert (data.status, data.method, data.amount, data.installments) == ("registered", "pix", 25000, 1)
    assert (data.issuer_kind, data.issuer_name, data.issuer_document) == (
        "practice",
        "Clínica Central Ltda",
        PRACTICE_CNPJ,
    )
    assert (data.professional_name, data.professional_council, data.professional_tax_id) == (
        "Dra. Ana",
        "CRM-SP 123456",
        DOCTOR_CPF,
    )
    assert (data.payer_name, data.payer_document) == ("Maria Fiscal", PATIENT_CPF)
    assert (data.beneficiary_name, data.beneficiary_document) == ("Maria Fiscal", PATIENT_CPF)
    assert data.description == "1x Consulta C1" and data.receipt_number
    payloads = repr([event.data for event in events])
    assert PATIENT_CPF not in payloads and "Maria" not in payloads and DOCTOR_CPF not in payloads


def test_a_desk_of_the_professional_issues_with_the_professional_cpf(ready):
    finance = FinanceService()
    patient = new_patient(ready, full_name="João Autônomo", cpf=PATIENT_CPF)
    with ready.as_user(ready.a.reception) as actor:
        desk = finance.desks(actor=actor)[0]
        assert desk.fiscal_issuer == "practice"
        changed = finance.set_fiscal_issuer(
            actor=actor, desk_id=desk.sysid, fiscal_issuer="professional", expected_revision=desk.revision
        )
        with pytest.raises(InvalidInput):
            finance.set_fiscal_issuer(
                actor=actor, desk_id=desk.sysid, fiscal_issuer="clinic", expected_revision=changed.revision
            )
        with pytest.raises(Conflict) as stale:
            finance.set_fiscal_issuer(
                actor=actor, desk_id=desk.sysid, fiscal_issuer="practice", expected_revision=desk.revision
            )
    assert changed.fiscal_issuer == "professional" and stale.value.code == "stale_revision"
    _appointment, _charge, payment, _events = _paid(ready, patient)
    with ready.as_user(ready.a.reception) as actor:
        data = finance.fiscal_data(actor=actor, payment_id=payment.sysid)
        assert (data.issuer_kind, data.issuer_name, data.issuer_document) == ("professional", "Dra. Ana", DOCTOR_CPF)
        # A charge without an appointment has no professional: the practice issues.
        other = finance.create_charge(
            actor=actor,
            patient_id=patient.sysid,
            items=(ChargeItemInput(code="C1"),),
            payer_name="Empresa Pagadora",
            payer_document=PRACTICE_CNPJ,
            idempotency_key="other",
        ).charge
        loose = finance.register_payment(
            actor=actor,
            charge_id=other.sysid,
            method="cash",
            amount=other.balance,
            expected_revision=other.revision,
            idempotency_key="loose",
        )
        data = finance.fiscal_data(actor=actor, payment_id=loose.sysid)
    assert (data.issuer_kind, data.issuer_document) == ("practice", PRACTICE_CNPJ)
    assert (data.payer_name, data.payer_document) == ("Empresa Pagadora", PRACTICE_CNPJ)
    assert (data.beneficiary_name, data.beneficiary_document) == ("João Autônomo", PATIENT_CPF)


def test_who_does_not_read_the_desk_gets_nothing_and_a_reversal_is_marked(ready):
    finance = FinanceService()
    patient = new_patient(ready, full_name="Ana Estorno", cpf=PATIENT_CPF)
    _appointment, _charge, payment, _events = _paid(ready, patient, issue_receipt=False)
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises(NotFound):
        finance.fiscal_data(actor=doctor, payment_id=payment.sysid)
    with ready.as_user(ready.b.reception, ready.org_b) as outsider, pytest.raises(NotFound):
        finance.fiscal_data(actor=outsider, payment_id=payment.sysid)
    with ready.as_user(ready.a.reception) as actor:
        desk = finance.desks(actor=actor)[0]
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises((NotFound, Forbidden)):
        finance.set_fiscal_issuer(
            actor=doctor, desk_id=desk.sysid, fiscal_issuer="professional", expected_revision=desk.revision
        )
    with ready.as_user(ready.a.reception) as actor:
        reversed_payment = finance.reverse_payment(
            actor=actor, payment_id=payment.sysid, reason="Pix devolvido", expected_revision=payment.revision
        )
        data = finance.fiscal_data(actor=actor, payment_id=payment.sysid)
    assert reversed_payment.status == "reversed"
    assert (data.status, data.receipt_number) == ("reversed", "")
