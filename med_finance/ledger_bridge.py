"""The only module of the finance app that calls the ledger (skeleton_ledger's LedgerService).

Titles, settlements and rule postings are authorized by the ledger through the source record
(the charge, the payment, the cash movement), so who works at a cash desk needs no access to the
book itself. Setting the book up (chart, keys, accounts) needs who manages the book.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

CHARGE_TABLE = "med_finance.charge"
MOVEMENT_TABLE = "med_finance.cashmovement"
# Extra accounts the finance app adds to the services chart: (code, name, kind, parent code).
EXTRA_ACCOUNTS = (
    ("1.4", "Pix a compensar", "asset", "1"),
    ("1.5", "Cartões a receber", "asset", "1"),
    ("3.2", "Aportes e retiradas do titular", "equity", "3"),
)
# Account key of the finance app -> account code of the chart.
BINDINGS = {
    "med_finance.service_revenue": "4.1",
    "med_finance.cash": "1.1",
    "med_finance.pix": "1.4",
    "med_finance.cards": "1.5",
    "med_finance.bank": "1.2",
    "med_finance.owner_transfers": "3.2",
}
# Payment method of a payment -> (payment account key on the desk, ledger settlement method).
METHODS = {
    "cash": ("cash", "cash"),
    "pix": ("pix", "pix"),
    "debit_card": ("cards", "card"),
    "credit_card": ("cards", "card"),
    "bank_transfer": ("bank", "transfer"),
    "other": ("bank", "other"),
}


def _ledger() -> Any:
    from skeleton.contrib.ledger.service_api import LedgerService

    return LedgerService()


def setup_book(actor: Any) -> tuple[UUID, dict[str, str]]:
    """The default book with the services chart, the finance accounts and keys; returns the book and the desk accounts."""
    ledger = _ledger()
    book = ledger.create_default_book(actor=actor)
    accounts = {item.code: item for item in ledger.accounts(actor=actor, book_id=book.sysid, page_size=100).items}
    if "4.1" not in accounts:
        ledger.apply_chart(actor=actor, book_id=book.sysid)
        accounts = {item.code: item for item in ledger.accounts(actor=actor, book_id=book.sysid, page_size=100).items}
    for code, name, kind, parent in EXTRA_ACCOUNTS:
        if code not in accounts:
            accounts[code] = ledger.create_account(
                actor=actor, code=code, name=name, kind=kind, book_id=book.sysid, parent_id=accounts[parent].sysid
            )
    bound = {item.code: item.account_id for item in ledger.account_keys(actor=actor, book_id=book.sysid)}
    for key, code in BINDINGS.items():
        if bound.get(key) is None:
            ledger.bind_key(actor=actor, key=key, account_id=accounts[code].sysid, book_id=book.sysid)
            bound[key] = accounts[code].sysid
    desk_accounts = {name: str(bound[f"med_finance.{name}"]) for name in ("cash", "pix", "cards", "bank")}
    return book.sysid, desk_accounts


def create_title(actor: Any, *, charge: Any, desk: Any, description: str, idempotency_key: str) -> UUID:
    title = _ledger().create_title(
        actor=actor,
        direction="receivable",
        amount=charge.total,
        due_date=charge.due_date,
        description=description,
        category_key="med_finance.service_revenue",
        idempotency_key=idempotency_key,
        party_ref=str(charge.patient_id),
        party_kind="med_patients.patient",
        source_table=CHARGE_TABLE,
        source_id=charge.pk,
        book_id=desk.book_id,
    )
    return title.sysid


def cancel_title(actor: Any, *, title_id: UUID, reason: str) -> None:
    ledger = _ledger()
    title = ledger.title(actor=actor, title_id=title_id)
    ledger.cancel_title(actor=actor, title_id=title_id, expected_revision=title.revision, reason=reason)


def settle(actor: Any, *, title_id: UUID, desk: Any, method: str, amount: int, on: date, idempotency_key: str) -> UUID:
    from skeleton.service_api import Conflict

    key, ledger_method = METHODS[method]
    account = (desk.payment_accounts or {}).get(key)
    if not account:
        raise Conflict("ledger_rejected", gettext("O caixa não tem a conta desta forma de pagamento no livro."))
    ledger = _ledger()
    title = ledger.title(actor=actor, title_id=title_id)
    settlement = ledger.settle_title(
        actor=actor,
        title_id=title_id,
        amount=amount,
        date=on,
        payment_account_id=UUID(account),
        method=ledger_method,
        expected_revision=title.revision,
        idempotency_key=idempotency_key,
    )
    return settlement.sysid


def reverse_settlement(actor: Any, *, title_id: UUID, settlement_id: UUID, on: date, reason: str) -> None:
    ledger = _ledger()
    settlement = next(
        item for item in ledger.settlements(actor=actor, title_id=title_id) if item.sysid == settlement_id
    )
    ledger.reverse_settlement(
        actor=actor, settlement_id=settlement_id, date=on, expected_revision=settlement.revision, reason=reason
    )


def post_movement(actor: Any, *, movement: Any, desk: Any, idempotency_key: str) -> UUID:
    rule = "med_finance.cash_supply" if movement.kind == "supply" else "med_finance.cash_withdrawal"
    entry = _ledger().post(
        actor=actor,
        rule=rule,
        amounts={"amount": movement.amount},
        date=movement.at.date(),
        description=movement.reason[:200],
        source_id=movement.pk,
        idempotency_key=idempotency_key,
        book_id=desk.book_id,
    )
    return entry.sysid
