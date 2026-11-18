"""Setup with the ledger book, and the price list."""

import pytest

from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound, Unavailable
from skeleton.testing.service_api import assert_service_contract

from ..service_api import FinanceService
from .helpers import add_price, prepare, setup_patients, setup_practice

KEYS = ("service_revenue", "cash", "pix", "cards", "bank", "owner_transfers")


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def test_service_contract():
    assert_service_contract(FinanceService)


def test_setup_prepares_the_book_and_is_idempotent(ready):
    with ready.as_user(ready.a.admin) as admin:
        (desk,) = service().desks(actor=admin)
        again = service().setup(actor=admin, idempotency_key="finance")
        assert again.sysid == desk.sysid
        with pytest.raises(Conflict):
            service().setup(actor=admin, idempotency_key="other")
        keys = {item.code: item.account_id for item in LedgerService().account_keys(actor=admin, book_id=desk.book_id)}
    assert all(keys[f"med_finance.{name}"] for name in KEYS)
    with ready.as_user(ready.a.reception) as actor:
        assert [item.sysid for item in service().desks(actor=actor)] == [desk.sysid]
        assert service().desks(actor=actor)[0].writable
        with pytest.raises(Forbidden):
            service().setup(actor=actor, idempotency_key="finance")
    with ready.as_user(ready.a.doctor) as doctor:
        assert service().desks(actor=doctor) == ()


def test_setup_without_the_ledger(clinic):
    setup_patients(clinic, clinic.a)
    setup_practice(clinic, clinic.a)
    with clinic.app_disabled("skeleton_ledger"), clinic.as_user(clinic.a.admin) as admin:
        with pytest.raises(Unavailable):
            service().setup(actor=admin, idempotency_key="off")
    from ..models import CashDesk, PriceList

    with clinic.as_user(clinic.a.admin):
        assert not CashDesk.objects.exists() and not PriceList.objects.exists()


def test_prices(ready):
    item = add_price(ready, "C1", 25000)
    assert add_price(ready, "C1", 25000).sysid == item.sysid
    with ready.as_user(ready.a.finance) as actor:
        with pytest.raises(Conflict):
            service().add_price_item(actor=actor, code="C1", description="Outra", amount=1, idempotency_key="dup")
        for amount in (-1, 1.5, "10"):
            with pytest.raises(InvalidInput):
                service().add_price_item(actor=actor, code="C2", description="X", amount=amount, idempotency_key="bad")
        changed = service().update_price_item(
            actor=actor, item_id=item.sysid, changes=(("amount", 30000),), expected_revision=item.revision
        )
        assert changed.amount == 30000
        with pytest.raises(Conflict):
            service().update_price_item(
                actor=actor, item_id=item.sysid, changes=(("amount", 1),), expected_revision=item.revision
            )
        with pytest.raises(InvalidInput):
            service().update_price_item(
                actor=actor, item_id=item.sysid, changes=(("code", "X"),), expected_revision=changed.revision
            )
        service().update_price_item(
            actor=actor, item_id=item.sysid, changes=(("is_active", False),), expected_revision=changed.revision
        )
        assert service().price_for(actor=actor, code="C1") is None
    add_price(ready, "C3", 10000)
    with ready.as_user(ready.a.reception) as actor:
        assert service().price_for(actor=actor, code="C3").amount == 10000
        with pytest.raises(Forbidden):
            service().add_price_item(actor=actor, code="C4", description="X", amount=1, idempotency_key="r")
    with ready.as_user(ready.b.finance, ready.org_b) as outsider:
        assert service().price_for(actor=outsider, code="C3") is None
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises(NotFound):
        service().price_items(actor=doctor)
