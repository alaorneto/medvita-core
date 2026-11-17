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
