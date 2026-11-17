"""Service API of the finance app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Money is an integer of the minor unit of the
currency (centavos), never a float. The ledger (skeleton_ledger) keeps titles, settlements and
reports; this app is the front desk: prices, charges, payments, cash sessions and receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import (
    Conflict,
    Forbidden,
    InvalidInput,
    NotFound,
    ServiceAPI,
    as_uuid,
    service_method,
)

from . import common
from .models import CashDesk, PriceItem, PriceList

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.finance"
DESK_TABLE = "med_finance.cashdesk"
PRICE_LIST_TABLE = "med_finance.pricelist"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (PRICE_LIST_TABLE, DESK_TABLE)
MAX_AMOUNT = 10**11  # R$ 1 bilhão em centavos: a sanity bound, not a business rule.

__all__ = [
    "APP_ID",
    "DeskInfo",
    "FinanceService",
    "PriceItemInfo",
    "PriceListInfo",
]


# --------------------------------------------------------------------------------------- DTOs


@dataclass(frozen=True, slots=True)
class DeskInfo:
    sysid: UUID
    name: str
    book_id: UUID
    price_list_id: UUID | None
    is_default: bool
    revision: int
    writable: bool = False


def desk_info(row: CashDesk, *, writable: bool = False) -> DeskInfo:
    return DeskInfo(row.pk, row.name, row.book_id, row.price_list_id, row.is_default, row.revision, writable)


@dataclass(frozen=True, slots=True)
class PriceListInfo:
    sysid: UUID
    name: str
    currency: str
    is_default: bool
    revision: int
    writable: bool = False


def price_list_info(row: PriceList, *, writable: bool = False) -> PriceListInfo:
    return PriceListInfo(row.pk, row.name, row.currency, row.is_default, row.revision, writable)


@dataclass(frozen=True, slots=True)
class PriceItemInfo:
    sysid: UUID
    price_list_id: UUID
    code: str
    description: str
    amount: int
    is_active: bool
    revision: int


def price_item_info(row: PriceItem) -> PriceItemInfo:
    return PriceItemInfo(row.pk, row.price_list_id, row.code, row.description, row.amount, row.is_active, row.revision)


# ------------------------------------------------------------------------------------ helpers


def _writable_ids(actor: Any, model: type) -> set[UUID]:
    from django.core.exceptions import PermissionDenied

    from skeleton.access.policies import authorized_queryset

    try:
        return set(authorized_queryset(model, user=actor, action="update").values_list("pk", flat=True))
    except PermissionDenied:
        return set()


def _container(actor: Any, model: type, record_id: object, *, field: str, write: bool = False, lock: bool = False):
    from skeleton.access.policies import authorized_queryset

    pk = as_uuid(record_id, field=field)
    if write:
        rows = authorized_queryset(model, user=actor, action="update").filter(pk=pk)
        found = (rows.select_for_update() if lock else rows).first()
        if found is not None:
            return found
    found = authorized_queryset(model, user=actor, action="read").filter(pk=pk).first()
    if found is None:
        raise NotFound()
    if write:
        raise Forbidden()
    return found


def _default(actor: Any, model: type, record_id: object, *, field: str, write: bool = False):
    """The record asked for, or the organization's default one the actor reads."""
    from skeleton.access.policies import authorized_queryset

    if record_id is not None:
        return _container(actor, model, record_id, field=field, write=write)
    row = authorized_queryset(model, user=actor, action="read").filter(is_default=True).first()
    if row is None:
        raise NotFound()
    if write:
        return _container(actor, model, row.pk, field=field, write=True)
    return row


def _name(value: object, field: str = "name") -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise InvalidInput({field: [gettext("Informe um nome de até 120 caracteres.")]})
    return value.strip()


def _amount(value: object, field: str = "amount", *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > MAX_AMOUNT:
        raise InvalidInput({field: [gettext("Informe um valor inteiro em centavos.")]})
    return value


def _clean_price(values: dict[str, Any]) -> dict[str, Any]:
    import re

    clean: dict[str, Any] = {}
    if "code" in values:
        code = values["code"]
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", code):
            raise InvalidInput({"code": [gettext("Use até 40 letras, números, ponto, hífen ou sublinhado.")]})
        clean["code"] = code
    if "description" in values:
        description = values["description"]
        if not isinstance(description, str) or not description.strip() or len(description) > 200:
            raise InvalidInput({"description": [gettext("Informe uma descrição de até 200 caracteres.")]})
        clean["description"] = description.strip()
    if "amount" in values:
        clean["amount"] = _amount(values["amount"])
    if "is_active" in values:
        if type(values["is_active"]) is not bool:
            raise InvalidInput({"is_active": [gettext("Use verdadeiro ou falso.")]})
        clean["is_active"] = values["is_active"]
    return clean


def _grant(actor: Any, table: str, record_id: UUID, groups: tuple[UUID, ...], actions: tuple[str, ...]) -> None:
    from skeleton.service_api.access import AccessService

    access = AccessService()
    for group in groups:
        for action in actions:
            access.grant_record_access(actor=actor, table_key=table, record_id=record_id, action=action, group_id=group)


# ------------------------------------------------------------------------------------ service


class FinanceService(ServiceAPI):
    """The clinic's front desk: prices, charges, payments, cash sessions and receipts, on top of the ledger."""

    app_label = APP_LABEL

    # ------------------------------------------------------------------ setup

    @service_method(read_only=False, since="0.1.0")
    def setup(
        self,
        *,
        actor: Any,
        desk_name: str = "",
        price_list_name: str = "",
        writer_group_ids: tuple[UUID, ...] = (),
        reader_group_ids: tuple[UUID, ...] = (),
        price_manager_group_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> DeskInfo:
        """Create the default price list and cash desk, and prepare the ledger book for them.

        Autorização: a capacidade ``access.manage``, ``create`` nas tabelas de preços e de caixas,
        e a gestão do livro contábil padrão (que é criado se não existir).
        Erros: Forbidden; InvalidInput para nome inválido ou mais de 20 grupos;
        Conflict("already_set_up") com um caixa padrão criado por outra chave; Unavailable com o
        livro contábil desativado.
        Efeitos: cria o livro padrão (se faltar), aplica o plano de serviços, cria as contas e
        vincula as chaves do financeiro; cria a tabela de preços e o caixa padrão (privados, do
        ator), dá ao papel ``member`` leitura e alteração das duas tabelas, concede leitura aos
        grupos de leitura, leitura e alteração do caixa aos de escrita e alteração da tabela de
        preços aos gestores de preço. A mesma chave devolve o já criado.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.access import AccessService
        from skeleton.tenancy.context import current_context

        from . import ledger_bridge

        key = common.key(idempotency_key)
        desk_label = _name(desk_name or gettext("Caixa da recepção"), "desk_name")
        list_label = _name(price_list_name or gettext("Tabela particular"), "price_list_name")
        writers = common.group_ids(writer_group_ids, "writer_group_ids")
        readers = tuple(
            group for group in common.group_ids(reader_group_ids, "reader_group_ids") if group not in writers
        )
        price_managers = common.group_ids(price_manager_group_ids, "price_manager_group_ids")
        common.require_access_manager(actor)
        if not (
            has_table_permission(CashDesk, user=actor, action="create")
            and has_table_permission(PriceList, user=actor, action="create")
        ):
            raise Forbidden()
        desk_id = common.deterministic_id("desk", actor, key)
        existing = CashDesk.objects.filter(pk=desk_id).first()
        if existing is not None:
            return desk_info(existing, writable=True)
        if CashDesk.objects.filter(is_default=True).exists():
            raise Conflict("already_set_up")
        book_id, accounts = ledger_bridge.setup_book(actor)
        organization = current_context().organization_id
        prices = PriceList(
            sysid=common.deterministic_id("price-list", actor, key),
            organization_id=organization,
            owner_id=actor.pk,
            visibility=PriceList.Visibility.PRIVATE,
            name=list_label,
            is_default=True,
        )
        prices.save()
        desk = CashDesk(
            sysid=desk_id,
            organization_id=organization,
            owner_id=actor.pk,
            visibility=CashDesk.Visibility.PRIVATE,
            name=desk_label,
            book_id=book_id,
            price_list=prices,
            payment_accounts=accounts,
            is_default=True,
        )
        desk.save()
        access = AccessService()
        for table in MEMBER_TABLES:
            access.grant_member_table_access(actor=actor, table_key=table, actions=("read", "update"))
        _grant(actor, PRICE_LIST_TABLE, prices.pk, writers + readers + price_managers, ("read",))
        _grant(actor, PRICE_LIST_TABLE, prices.pk, price_managers, ("update",))
        _grant(actor, DESK_TABLE, desk.pk, writers + readers, ("read",))
        _grant(actor, DESK_TABLE, desk.pk, writers, ("update",))
        return desk_info(desk, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def desks(self, *, actor: Any) -> tuple[DeskInfo, ...]:
        """The cash desks the actor reads, the default first.

        Autorização: leitura de cada caixa.
        Erros: nenhum além do contrato.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(CashDesk, user=actor, action="read").order_by("-is_default", "name", "sysid")
        writable = _writable_ids(actor, CashDesk)
        return tuple(desk_info(row, writable=row.pk in writable) for row in rows[:100])

    @service_method(read_only=True, since="0.1.0")
    def price_lists(self, *, actor: Any) -> tuple[PriceListInfo, ...]:
        """The price lists the actor reads, the default first.

        Autorização: leitura de cada tabela de preços.
        Erros: nenhum além do contrato.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(PriceList, user=actor, action="read").order_by("-is_default", "name", "sysid")
        writable = _writable_ids(actor, PriceList)
        return tuple(price_list_info(row, writable=row.pk in writable) for row in rows[:100])

    # ------------------------------------------------------------------ prices

    @service_method(read_only=True, since="0.1.0")
    def price_items(
        self, *, actor: Any, price_list_id: UUID | None = None, query: str = "", active_only: bool = True
    ) -> tuple[PriceItemInfo, ...]:
        """Items of a price list (the default one when not informed), by code.

        Autorização: leitura da tabela de preços.
        Erros: NotFound para tabela ilegível ou sem tabela padrão; InvalidInput para busca longa demais.
        Efeitos: nenhum.
        """
        from django.db.models import Q

        from skeleton.access.policies import authorized_queryset

        if not isinstance(query, str) or len(query) > 100:
            raise InvalidInput({"query": [gettext("Use até 100 caracteres.")]})
        prices = _default(actor, PriceList, price_list_id, field="price_list_id")
        rows = authorized_queryset(PriceItem, user=actor, action="read").filter(price_list=prices)
        if active_only:
            rows = rows.filter(is_active=True)
        if query.strip():
            rows = rows.filter(Q(code__icontains=query.strip()) | Q(description__icontains=query.strip()))
        return tuple(price_item_info(row) for row in rows.order_by("code", "sysid")[:500])

    @service_method(read_only=True, since="0.1.0")
    def price_for(self, *, actor: Any, code: str, price_list_id: UUID | None = None) -> PriceItemInfo | None:
        """The active item of a code (the appointment type's billing code), or ``None``.

        Autorização: leitura da tabela de preços.
        Erros: NotFound para tabela ilegível ou sem tabela padrão.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        prices = _default(actor, PriceList, price_list_id, field="price_list_id")
        row = (
            authorized_queryset(PriceItem, user=actor, action="read")
            .filter(price_list=prices, code=str(code), is_active=True)
            .first()
        )
        return price_item_info(row) if row is not None else None

    @service_method(read_only=False, since="0.1.0")
    def add_price_item(
        self,
        *,
        actor: Any,
        code: str,
        description: str,
        amount: int,
        price_list_id: UUID | None = None,
        idempotency_key: str,
    ) -> PriceItemInfo:
        """Add an item to a price list (the default one when not informed).

        Autorização: alteração na tabela de preços.
        Erros: NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("integrity_conflict")
        para código repetido na tabela.
        Efeitos: grava o item. A mesma chave devolve o já gravado.
        """
        from skeleton.access.policies import require_parent_action

        key = common.key(idempotency_key)
        values = _clean_price({"code": code, "description": description, "amount": amount})
        sysid = common.deterministic_id("price-item", actor, key)
        existing = PriceItem.objects.filter(pk=sysid).first()
        if existing is not None:
            return price_item_info(existing)
        prices = _default(actor, PriceList, price_list_id, field="price_list_id", write=True)
        require_parent_action(PriceItem, prices, user=actor, action="create")
        row = PriceItem(sysid=sysid, organization_id=prices.organization_id, price_list=prices, **values)
        row.save()
        return price_item_info(row)

    @service_method(read_only=False, since="0.1.0")
    def update_price_item(
        self, *, actor: Any, item_id: UUID, changes: tuple[tuple[str, Any], ...], expected_revision: int
    ) -> PriceItemInfo:
        """Change the description, amount or activity of a price item, with CAS (the code never changes).

        Autorização: alteração na tabela de preços.
        Erros: NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
        Efeitos: grava só os campos que mudaram; contas já confirmadas não mudam.
        """
        values = common.changes_dict(changes)
        common.refuse_unknown(values, ("description", "amount", "is_active"))
        clean = _clean_price(values)
        row = common.row(actor, PriceItem, item_id, field="item_id", write=True, lock=True)
        common.check_revision(row, expected_revision)
        common.apply_changes(row, clean)
        return price_item_info(row)
