"""Charges: draft, confirmation with a receivable title in the ledger, cancellation, origins and events."""

import pytest

from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound

from ..extension import isolated_origins
from ..service_api import ChargeItemInput, ChargeOrigin, FinanceService, register_charge_origin
from .helpers import add_price, new_patient, prepare

CPF = "52998224725"


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    return clinic


def create(ready, patient, *, key="charge", user=None, **values):
    values.setdefault("items", (ChargeItemInput(code="C1"),))
    with ready.as_user(user or ready.a.reception) as actor:
        return service().create_charge(actor=actor, patient_id=patient.sysid, idempotency_key=key, **values)


def test_confirmed_charge_becomes_a_title_without_personal_data(ready, monkeypatch):
    patient = new_patient(ready, full_name="Pagador Secreto")
    published = []
    from skeleton.service_api.events import EventService

    original = EventService.publish
    monkeypatch.setattr(EventService, "publish", lambda self, **kw: published.append(kw) or original(self, **kw))
    detail = create(
        ready,
        patient,
        items=(
            ChargeItemInput(code="C1"),
            ChargeItemInput(description="Curativo", unit_amount=3000, quantity=2, discount_amount=1000),
        ),
        payer_name="Responsável Secreto",
        payer_document=CPF,
    )
    charge = detail.charge
    assert charge.code.startswith("C") and charge.status == "open" and charge.total == 25000 + 5000
    assert [item.total for item in detail.items] == [25000, 5000]
    assert create(ready, patient).charge.sysid == charge.sysid
    with ready.as_user(ready.a.reception) as actor:
        (title,) = LedgerService().titles_for_source(
            actor=actor, table_key="med_finance.charge", record_id=charge.sysid
        )
        assert service().patient_balance(actor=actor, patient_id=patient.sysid) == 30000
    assert title.sysid == charge.ledger_title_id and title.amount == 30000 and title.party_ref == str(patient.sysid)
    assert "Secreto" not in repr(title) and CPF not in repr(title)
    (event,) = published
    assert event["event_type"] == "med_finance.charge_confirmed" and "Secreto" not in repr(event)


def test_draft_items_confirmation_and_validation(ready, subtests):
    patient = new_patient(ready)
    draft = create(ready, patient, key="draft", confirm=False).charge
    assert draft.status == "draft" and draft.ledger_title_id is None
    with ready.as_user(ready.a.reception) as actor:
        more = service().add_item(
            actor=actor,
            charge_id=draft.sysid,
            item=ChargeItemInput(description="Taxa", unit_amount=1000),
            expected_revision=draft.revision,
        )
        assert more.charge.total == 26000
        with pytest.raises(Conflict):
            service().add_item(
                actor=actor, charge_id=draft.sysid, item=ChargeItemInput(code="C1"), expected_revision=draft.revision
            )
        fewer = service().remove_item(
            actor=actor, charge_id=draft.sysid, item_id=more.items[1].sysid, expected_revision=more.charge.revision
        )
        confirmed = service().confirm_charge(
            actor=actor, charge_id=draft.sysid, expected_revision=fewer.charge.revision
        )
        assert confirmed.charge.status == "open" and confirmed.charge.total == 25000
        with pytest.raises(Conflict):
            service().confirm_charge(actor=actor, charge_id=draft.sysid, expected_revision=confirmed.charge.revision)
    cases = {
        "unknown code": {"items": (ChargeItemInput(code="NOPE"),)},
        "no items": {"items": ()},
        "bad discount": {"items": (ChargeItemInput(description="X", unit_amount=100, discount_amount=200),)},
        "bad payer": {"payer_document": "123"},
        "zero total": {"items": (ChargeItemInput(description="X", unit_amount=0),)},
        "unregistered origin": {"origin_app": "med_example", "origin_key": "x"},
    }
    for name, values in cases.items():
        with subtests.test(name), pytest.raises(InvalidInput):
            create(ready, patient, key=f"bad-{name}", **values)


def test_cancel(ready):
    patient = new_patient(ready)
    charge = create(ready, patient).charge
    with ready.as_user(ready.a.reception) as actor:
        with pytest.raises(InvalidInput):
            service().cancel_charge(actor=actor, charge_id=charge.sysid, reason="", expected_revision=charge.revision)
        cancelled = service().cancel_charge(
            actor=actor, charge_id=charge.sysid, reason="Lançada por engano", expected_revision=charge.revision
        )
        assert cancelled.charge.status == "cancelled"
        (title,) = LedgerService().titles_for_source(
            actor=actor, table_key="med_finance.charge", record_id=charge.sysid
        )
        assert title.status == "cancelled"
        assert service().patient_balance(actor=actor, patient_id=patient.sysid) == 0


def test_origin_returns_the_same_charge(ready):
    patient = new_patient(ready)
    with isolated_origins():
        register_charge_origin(ChargeOrigin("med_scheduling", "Agenda"))
        first = create(ready, patient, key="o1", origin_app="med_scheduling", origin_key="appointment-1").charge
        again = create(ready, patient, key="o2", origin_app="med_scheduling", origin_key="appointment-1").charge
        assert again.sysid == first.sysid
        with ready.as_user(ready.a.reception) as actor:
            (found,) = service().charges_for_origin(
                actor=actor, origin_app="med_scheduling", origin_key="appointment-1"
            )
        assert found.sysid == first.sysid
        with pytest.raises(ValueError):
            register_charge_origin(ChargeOrigin("med_scheduling", "Outra"))


def test_authorization_and_isolation(ready):
    patient = new_patient(ready)
    charge = create(ready, patient).charge
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(NotFound):
            service().charge(actor=doctor, charge_id=charge.sysid)
        assert service().charges(actor=doctor).items == ()
    with ready.as_user(ready.b.reception, ready.org_b) as outsider, pytest.raises(NotFound):
        service().cancel_charge(actor=outsider, charge_id=charge.sysid, reason="x", expected_revision=charge.revision)
    with ready.as_user(ready.a.admin) as admin:
        from skeleton.service_api.access import AccessService

        (desk,) = service().desks(actor=admin)
        AccessService().grant_record_access(
            actor=admin,
            table_key="med_finance.cashdesk",
            record_id=desk.sysid,
            action="read",
            group_id=ready.a.groups["professionals"],
        )
    with ready.as_user(ready.a.doctor) as doctor:
        assert service().charge(actor=doctor, charge_id=charge.sysid).writable is False
        with pytest.raises(Forbidden):
            service().cancel_charge(actor=doctor, charge_id=charge.sysid, reason="x", expected_revision=charge.revision)
