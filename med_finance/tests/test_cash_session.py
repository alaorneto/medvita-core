"""Cash sessions: opening, supplies and withdrawals posted to the ledger, closing with the difference."""

import pytest

from skeleton.contrib.ledger.service_api import LedgerService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound

from ..service_api import FinanceService
from .helpers import prepare


def service():
    return FinanceService()


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def open_session(ready, user=None, amount=10000, key="open"):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().open_session(actor=actor, opening_amount=amount, idempotency_key=key)


def move(ready, session, kind, amount, key, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return service().add_movement(
            actor=actor, session_id=session.sysid, kind=kind, amount=amount, reason="Troco", idempotency_key=key
        )


def test_open_move_and_close(ready, subtests):
    session = open_session(ready)
    assert open_session(ready).sysid == session.sysid
    with pytest.raises(Conflict) as error:
        open_session(ready, key="second")
    assert error.value.code == "session_already_open"
    supply = move(ready, session, "supply", 5000, "s1")
    assert move(ready, session, "supply", 5000, "s1").sysid == supply.sysid
    move(ready, session, "withdrawal", 3000, "w1")
    with pytest.raises(Conflict) as error:
        move(ready, session, "withdrawal", 100000, "w2")
    assert error.value.code == "insufficient_cash"
    for kind, amount in (("gift", 10), ("supply", 0), ("supply", -5)):
        with subtests.test(kind=kind, amount=amount), pytest.raises(InvalidInput):
            move(ready, session, kind, amount, f"bad-{kind}-{amount}")
    with ready.as_user(ready.a.reception) as actor:
        report = service().session_report(actor=actor, session_id=session.sysid)
        assert (report.supplies, report.withdrawals, report.expected_cash) == (5000, 3000, 12000)
        closed = service().close_session(
            actor=actor, session_id=session.sysid, counted_amount=11500, expected_revision=session.revision
        )
    assert (closed.expected_amount, closed.difference, closed.status) == (12000, -500, "closed")
    with pytest.raises(Conflict) as error:
        move(ready, session, "supply", 100, "late")
    assert error.value.code == "session_closed"
    assert open_session(ready, key="next").sysid != session.sysid


def test_movements_are_posted_to_the_ledger(ready):
    session = open_session(ready)
    supply = move(ready, session, "supply", 5000, "s1")
    with ready.as_user(ready.a.reception) as actor:
        (entry,) = LedgerService().entries_for_source(
            actor=actor, table_key="med_finance.cashmovement", record_id=supply.sysid
        )
    assert entry.sysid == supply.ledger_entry_id and entry.total == 5000


def test_only_the_opener_or_a_manager_closes(ready):
    session = open_session(ready)
    with ready.as_user(ready.a.finance) as other, pytest.raises(Forbidden):
        service().close_session(actor=other, session_id=session.sysid, counted_amount=0, expected_revision=1)
    with ready.as_user(ready.a.admin) as admin:
        assert (
            service()
            .close_session(
                actor=admin, session_id=session.sysid, counted_amount=10000, expected_revision=session.revision
            )
            .difference
            == 0
        )
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises(NotFound):
        service().current_session(actor=doctor)
    with ready.as_user(ready.b.reception, ready.org_b) as outsider, pytest.raises(NotFound):
        service().session_report(actor=outsider, session_id=session.sysid)
