"""Tables, account keys, sequences, events and contributions of the finance app, registered in ``ready()``."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

APP_LABEL = "med_finance"


def _name_update(record, *, user, values):
    """Generic gateway update of a container: only its name."""
    for name, value in values.items():
        setattr(record, name, value)
    record.save(update_fields=set(values))


def register_price_and_desk_tables() -> None:
    from skeleton.system.record_operations import RecordOperations, register_record_operations
    from skeleton.system.registry import TableSpec, register

    from .models import CashDesk, PriceItem, PriceList

    register(
        TableSpec(
            model=PriceList,
            description=_("Tabelas de preços do consultório."),
            label=_("Tabelas de preços"),
            scope="organization",
            read_fields=("name", "currency", "is_default", "owner", "visibility"),
            write_fields=("name",),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    register_record_operations("med_finance.pricelist", RecordOperations(update=_name_update))
    register(
        TableSpec(
            model=PriceItem,
            description=_("Itens de uma tabela de preços; o código é o código de cobrança da agenda."),
            label=_("Itens de preço"),
            scope="organization",
            read_fields=("price_list", "code", "description", "amount", "is_active"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="price_list",
        )
    )
    register(
        TableSpec(
            model=CashDesk,
            description=_("Caixas: pontos de recebimento ligados a um livro contábil."),
            label=_("Caixas"),
            scope="organization",
            read_fields=("name", "book", "price_list", "is_default", "owner", "visibility"),
            write_fields=("name",),
            sensitive_fields=(),
            expose_api=True,
        )
    )
    register_record_operations("med_finance.cashdesk", RecordOperations(update=_name_update))


ACCOUNT_KEYS = (
    ("service_revenue", "Receita de atendimentos", "revenue"),
    ("cash", "Dinheiro em caixa", "asset"),
    ("pix", "Pix a compensar", "asset"),
    ("cards", "Cartões a receber", "asset"),
    ("bank", "Banco", "asset"),
    ("owner_transfers", "Aportes e retiradas do titular", "equity"),
)


def register_account_keys() -> None:
    from skeleton.contrib.ledger.service_api import AccountKey, register_account_key

    for name, label, kind in ACCOUNT_KEYS:
        register_account_key(AccountKey(code=f"{APP_LABEL}.{name}", label=label, kind=kind))


def register_contributions() -> None:
    from applications.med_patients.service_api import SetupStep, register_setup_step

    register_setup_step(SetupStep("med_finance.desk", _("Financeiro"), "med_finance:setup", _has_desk, order=40))


def _has_desk(*, actor) -> bool:
    from .service_api import FinanceService

    return bool(FinanceService().desks(actor=actor))


def register_cash_tables() -> None:
    from skeleton.contrib.ledger.service_api import Key, PostingRule, RuleLine, register_posting_rule
    from skeleton.system.registry import TableSpec, register

    from .models import CashMovement, CashSession

    register(
        TableSpec(
            model=CashSession,
            description=_("Sessões de caixa: abertura, fechamento e a diferença contada."),
            label=_("Sessões de caixa"),
            scope="organization",
            read_fields=(
                "desk",
                "opened_by",
                "opened_at",
                "opening_amount",
                "status",
                "closed_by",
                "closed_at",
                "counted_amount",
                "expected_amount",
                "difference",
                "note",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="desk",
        )
    )
    register(
        TableSpec(
            model=CashMovement,
            description=_("Suprimentos e sangrias de uma sessão de caixa, lançados no livro."),
            label=_("Movimentos de caixa"),
            scope="organization",
            read_fields=("session", "kind", "amount", "reason", "at", "ledger_entry"),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="session",
        )
    )
    for code, label, debit, credit in (
        ("cash_supply", "Suprimento de caixa", "med_finance.cash", "med_finance.owner_transfers"),
        ("cash_withdrawal", "Sangria de caixa", "med_finance.owner_transfers", "med_finance.cash"),
    ):
        register_posting_rule(
            PostingRule(
                code=f"{APP_LABEL}.{code}",
                label=label,
                source_table_key="med_finance.cashmovement",
                source_action="update",
                lines=(RuleLine("debit", Key(debit), "amount"), RuleLine("credit", Key(credit), "amount")),
            )
        )


CHARGE_SEQUENCE = "med_finance.charge"
CHARGE_EVENTS = ("confirmed", "paid", "cancelled")


def register_charges() -> None:
    from skeleton.events.registry import EventType, register_event_type
    from skeleton.sequences.registry import SequenceSpec, register_sequence
    from skeleton.system.registry import TableSpec, register

    from .models import Charge, ChargeItem

    register(
        TableSpec(
            model=Charge,
            description=_("Contas do paciente no caixa; confirmadas viram títulos a receber no livro."),
            label=_("Contas"),
            scope="organization",
            read_fields=(
                "desk",
                "code",
                "patient",
                "payer_name",
                "payer_document",
                "status",
                "total",
                "paid_total",
                "due_date",
                "origin_app",
                "origin_key",
                "appointment",
                "ledger_title",
                "note",
                "confirmed_at",
                "cancelled_at",
                "cancel_reason",
            ),
            write_fields=(),
            sensitive_fields=(),
            personal_fields=("payer_name", "payer_document"),
            expose_api=False,
            access_parent="desk",
        )
    )
    register(
        TableSpec(
            model=ChargeItem,
            description=_("Itens de uma conta."),
            label=_("Itens de conta"),
            scope="organization",
            read_fields=(
                "charge",
                "price_item",
                "code",
                "description",
                "quantity",
                "unit_amount",
                "discount_amount",
                "total",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="charge",
        )
    )
    register_sequence(SequenceSpec(key=CHARGE_SEQUENCE, period="none", template="C{number:08d}", owner_app=APP_LABEL))
    for name in CHARGE_EVENTS:
        register_event_type(
            EventType(
                code=f"{APP_LABEL}.charge_{name}",
                table_key="med_finance.charge",
                payload_fields=("code", "desk", "patient", "status", "total", "origin_app", "origin_key"),
                owner_app=APP_LABEL,
            )
        )


def register_payments() -> None:
    from skeleton.events.registry import EventType, register_event_type
    from skeleton.system.registry import TableSpec, register

    from .models import Payment

    register(
        TableSpec(
            model=Payment,
            description=_("Pagamentos das contas, recebidos numa sessão de caixa e baixados no livro."),
            label=_("Pagamentos"),
            scope="organization",
            read_fields=(
                "charge",
                "session",
                "method",
                "amount",
                "received_at",
                "installments",
                "authorization_code",
                "received_by",
                "status",
                "reversed_at",
                "reverse_reason",
                "ledger_settlement",
            ),
            write_fields=(),
            sensitive_fields=(),
            expose_api=False,
            access_parent="charge",
        )
    )
    for name in ("registered", "reversed"):
        register_event_type(
            EventType(
                code=f"{APP_LABEL}.payment_{name}",
                table_key="med_finance.payment",
                payload_fields=("charge", "method", "amount", "status"),
                owner_app=APP_LABEL,
            )
        )
