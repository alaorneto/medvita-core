"""Receipts: numbered per year without gaps, sealed at issue, voided by a record, never reused."""

from datetime import UTC, datetime

import pytest

from skeleton.service_api import Conflict
from skeleton.service_api.sequences import SequenceService
from skeleton.testing.sealing import assert_sealed_contract

from ..models import Receipt
from ..service_api import ChargeItemInput, FinanceService, receipt_extra
from .helpers import add_price, new_patient, prepare


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    with clinic.as_user(clinic.a.reception) as actor:
        service().open_session(actor=actor, idempotency_key="open")
    return clinic


def paid(ready, key, *, receipt=True, patient=None):
    patient = patient or new_patient(ready, full_name="Maria Recibo")
    with ready.as_user(ready.a.reception) as actor:
        charge = (
            service()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key=key
            )
            .charge
        )
        return service().register_payment(
            actor=actor,
            charge_id=charge.sysid,
            method="pix",
            amount=charge.total,
            expected_revision=charge.revision,
            idempotency_key=f"pay-{key}",
            issue_receipt=receipt,
        )


def receipts(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().receipts(actor=actor).items


def test_payment_issues_a_sealed_receipt(ready):
    payment = paid(ready, "a")
    (receipt,) = receipts(ready)
    year = datetime.now(UTC).year
    assert receipt.payment_id == payment.sysid and receipt.number == f"{year}/000001"
    assert receipt.patient_name == "Maria Recibo" and receipt.payer_name == "Maria Recibo"
    assert receipt.issuer_name == "Consultório Central" and receipt.amount == 25000
    with ready.as_user(ready.a.reception) as actor:
        assert service().issue_receipt(actor=actor, payment_id=payment.sysid, idempotency_key="again").sysid == (
            receipt.sysid
        )
        assert service().verify_receipt(actor=actor, receipt_id=receipt.sysid)


def test_numbers_are_consecutive_and_restart_each_year(ready):
    for key in "abcde":
        paid(ready, key)
    numbers = sorted(item.number for item in receipts(ready))
    year = datetime.now(UTC).year
    assert numbers == [f"{year}/{n:06d}" for n in range(1, 6)]
    with ready.as_user(ready.a.reception) as actor:
        later = SequenceService().next_number(
            actor=actor, key="med_finance.receipt", at=datetime(year + 1, 1, 2, tzinfo=UTC)
        )
    assert later.formatted == f"{year + 1}/000001"


def test_void_keeps_the_receipt_and_allows_reversal(ready):
    payment = paid(ready, "a")
    (receipt,) = receipts(ready)
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(Conflict) as error:
            service().reverse_payment(
                actor=actor, payment_id=payment.sysid, reason="x", expected_revision=payment.revision
            )
        assert error.value.code == "receipt_not_voided"
        voided = service().void_receipt(
            actor=actor, receipt_id=receipt.sysid, reason="Emitido errado", idempotency_key="v"
        )
        assert voided.voided and voided.number == receipt.number
        assert service().verify_receipt(actor=actor, receipt_id=receipt.sysid)
        current = next(item for item in service().payments(actor=actor, charge_id=payment.charge_id))
        service().reverse_payment(
            actor=actor, payment_id=payment.sysid, reason="Duplicado", expected_revision=current.revision
        )
    paid(ready, "b")
    year = datetime.now(UTC).year
    assert sorted(item.number for item in receipts(ready)) == [f"{year}/000001", f"{year}/000002"]


def test_seal_contract(ready):
    reception = ready.a.reception  # acting() opens the reception's context around make_record and seal.
    keys = iter(range(100))
    patient = new_patient(ready)

    def make_record():
        number = next(keys)
        charge = (
            service()
            .create_charge(
                actor=reception,
                patient_id=patient.sysid,
                items=(ChargeItemInput(code="C1"),),
                idempotency_key=f"s{number}",
            )
            .charge
        )
        payment = service().register_payment(
            actor=reception,
            charge_id=charge.sysid,
            method="cash",
            amount=charge.total,
            expected_revision=charge.revision,
            idempotency_key=f"sp{number}",
            issue_receipt=False,
        )
        # The receipt is sealed at issue; the kit needs an unsealed one first, so build it like the service does.
        from ..models import Payment

        row = Payment.objects.get(pk=payment.sysid)
        receipt = Receipt(
            organization_id=row.organization_id,
            charge_id=row.charge_id,
            payment=row,
            number=f"T/{number}",
            issued_at=datetime(2026, 1, 1, tzinfo=UTC),
            amount=row.amount,
            method=row.method,
            payer_name="Pagador",
            patient_name="Paciente",
            description="Consulta",
            issuer_name="Consultório",
        )
        receipt.save()
        return receipt

    def seal(record):
        from skeleton.records.sealing import seal_record

        return seal_record(record, user=reception, expected_revision=record.revision, extra=receipt_extra(record))

    assert_sealed_contract(
        Receipt,
        make_record=make_record,
        seal=seal,
        acting=lambda: ready.as_user(ready.a.reception),
        foreign=lambda: ready.as_user(ready.b.reception, ready.org_b),
        extra=receipt_extra,
    )
