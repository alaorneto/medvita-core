"""Service API of the finance app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Money is an integer of the minor unit of the
currency (centavos), never a float. The ledger (skeleton_ledger) keeps titles, settlements and
reports; this app is the front desk: prices, charges, payments, cash sessions and receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext

from skeleton.service_api import (
    Conflict,
    Forbidden,
    InvalidInput,
    NotFound,
    Page,
    ServiceAPI,
    as_utc,
    as_uuid,
    paginate,
    service_method,
)

from . import common
from .extension import ChargeOrigin, register_charge_origin
from .models import CashDesk, CashMovement, CashSession, Charge, ChargeItem, Payment, PriceItem, PriceList

APP_LABEL = common.APP_LABEL
APP_ID = "io.katua.sk.med.finance"
DESK_TABLE = "med_finance.cashdesk"
PRICE_LIST_TABLE = "med_finance.pricelist"
# Container tables the built-in member role gets read and update on (the records decide the rest).
MEMBER_TABLES = (PRICE_LIST_TABLE, DESK_TABLE)
MAX_AMOUNT = 10**11  # R$ 1 bilhão em centavos: a sanity bound, not a business rule.

__all__ = [
    "PaymentInfo",
    "ChargeDetail",
    "ChargeInfo",
    "ChargeItemInfo",
    "ChargeItemInput",
    "ChargeOrigin",
    "register_charge_origin",
    "MethodTotal",
    "MovementInfo",
    "SessionInfo",
    "SessionReport",
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


@dataclass(frozen=True, slots=True)
class SessionInfo:
    sysid: UUID
    desk_id: UUID
    opened_by_id: UUID
    opened_at: datetime
    opening_amount: int
    status: str
    closed_by_id: UUID | None
    closed_at: datetime | None
    counted_amount: int | None
    expected_amount: int | None
    difference: int | None
    note: str
    revision: int


def session_info(row: CashSession) -> SessionInfo:
    return SessionInfo(
        row.pk,
        row.desk_id,
        row.opened_by_id,
        as_utc(row.opened_at),
        row.opening_amount,
        row.status,
        row.closed_by_id,
        as_utc(row.closed_at) if row.closed_at else None,
        row.counted_amount,
        row.expected_amount,
        row.difference,
        row.note,
        row.revision,
    )


@dataclass(frozen=True, slots=True)
class MovementInfo:
    sysid: UUID
    session_id: UUID
    kind: str
    amount: int
    reason: str
    at: datetime
    ledger_entry_id: UUID | None


def movement_info(row: CashMovement) -> MovementInfo:
    return MovementInfo(row.pk, row.session_id, row.kind, row.amount, row.reason, as_utc(row.at), row.ledger_entry)


@dataclass(frozen=True, slots=True)
class MethodTotal:
    method: str
    amount: int
    count: int


@dataclass(frozen=True, slots=True)
class SessionReport:
    session: SessionInfo
    by_method: tuple[MethodTotal, ...]
    supplies: int
    withdrawals: int
    expected_cash: int
    movements: tuple[MovementInfo, ...]


def _payments_by_method(actor: Any, session: CashSession) -> tuple[MethodTotal, ...]:
    """Registered (not reversed) payments of the session, by method."""
    from django.db.models import Count, Sum

    from skeleton.access.policies import authorized_queryset

    rows = (
        authorized_queryset(Payment, user=actor, action="read")
        .filter(session=session, status="registered")
        .values("method")
        .annotate(total=Sum("amount"), count=Count("sysid"))
        .order_by("method")
    )
    return tuple(MethodTotal(row["method"], row["total"] or 0, row["count"]) for row in rows)


def _cash_payments(session: CashSession) -> int:
    """Cash payments of the session that were not reversed."""
    from django.db.models import Sum

    total = Payment.objects.filter(session=session, method="cash", status="registered").aggregate(total=Sum("amount"))
    return int(total["total"] or 0)


def _expected_cash(session: CashSession) -> int:
    """Opening cash + cash payments + supplies - withdrawals of the session."""
    from django.db.models import Sum

    totals = {
        row["kind"]: row["total"]
        for row in CashMovement.objects.filter(session=session).values("kind").annotate(total=Sum("amount"))
    }
    return (
        session.opening_amount + _cash_payments(session) + (totals.get("supply") or 0) - (totals.get("withdrawal") or 0)
    )


class _ledger_errors:
    """Turn a refusal of the ledger (period locked, unbound key) into Conflict("ledger_rejected")."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, error: Any, traceback: Any) -> bool:
        if isinstance(error, Conflict) and error.code != "ledger_rejected":
            raise Conflict("ledger_rejected", gettext("O livro contábil recusou o lançamento.")) from error
        return False


@dataclass(frozen=True, slots=True)
class ChargeItemInput:
    """A line to bill: with ``code`` and no ``unit_amount``, the price comes from the desk's price list."""

    code: str = ""
    description: str = ""
    quantity: int = 1
    unit_amount: int | None = None
    discount_amount: int = 0


@dataclass(frozen=True, slots=True)
class ChargeItemInfo:
    sysid: UUID
    code: str
    description: str
    quantity: int
    unit_amount: int
    discount_amount: int
    total: int


def charge_item_info(row: ChargeItem) -> ChargeItemInfo:
    return ChargeItemInfo(
        row.pk, row.code, row.description, row.quantity, row.unit_amount, row.discount_amount, row.total
    )


@dataclass(frozen=True, slots=True)
class ChargeInfo:
    sysid: UUID
    desk_id: UUID
    code: str
    patient_id: UUID
    payer_name: str
    payer_document: str
    status: str
    total: int
    paid_total: int
    balance: int
    due_date: date
    origin_app: str
    origin_key: str
    appointment_id: UUID | None
    ledger_title_id: UUID | None
    note: str
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str
    revision: int


def charge_info(row: Charge) -> ChargeInfo:
    return ChargeInfo(
        row.pk,
        row.desk_id,
        row.code,
        row.patient_id,
        row.payer_name,
        row.payer_document,
        row.status,
        row.total,
        row.paid_total,
        row.total - row.paid_total if row.status in ("open", "partially_paid") else 0,
        row.due_date,
        row.origin_app,
        row.origin_key,
        row.appointment_id,
        row.ledger_title,
        row.note,
        as_utc(row.confirmed_at) if row.confirmed_at else None,
        as_utc(row.cancelled_at) if row.cancelled_at else None,
        row.cancel_reason,
        row.revision,
    )


@dataclass(frozen=True, slots=True)
class ChargeDetail:
    charge: ChargeInfo
    items: tuple[ChargeItemInfo, ...]
    writable: bool


CHARGE_EVENT_PAYLOAD = ("code", "desk", "patient", "status", "total", "origin_app", "origin_key")


def _publish_charge(actor: Any, suffix: str, row: Charge) -> None:
    from skeleton.service_api.events import EventService

    EventService().publish(
        actor=actor,
        event_type=f"med_finance.charge_{suffix}",
        record_id=row.pk,
        data=(
            ("code", row.code),
            ("desk", str(row.desk_id)),
            ("patient", str(row.patient_id)),
            ("status", row.status),
            ("total", row.total),
            ("origin_app", row.origin_app),
            ("origin_key", row.origin_key),
        ),
    )


def _has_active_payments(charge: Charge) -> bool:
    """Whether the charge has a registered (not reversed) payment."""
    return Payment.objects.filter(charge=charge, status="registered").exists()


@dataclass(frozen=True, slots=True)
class PaymentInfo:
    sysid: UUID
    charge_id: UUID
    session_id: UUID
    method: str
    amount: int
    received_at: datetime
    installments: int
    authorization_code: str
    received_by_id: UUID
    status: str
    reversed_at: datetime | None
    reverse_reason: str
    ledger_settlement_id: UUID | None
    revision: int


def payment_info(row: Payment) -> PaymentInfo:
    return PaymentInfo(
        row.pk,
        row.charge_id,
        row.session_id,
        row.method,
        row.amount,
        as_utc(row.received_at),
        row.installments,
        row.authorization_code,
        row.received_by_id,
        row.status,
        as_utc(row.reversed_at) if row.reversed_at else None,
        row.reverse_reason,
        row.ledger_settlement,
        row.revision,
    )


def _publish_payment(actor: Any, suffix: str, row: Payment) -> None:
    from skeleton.service_api.events import EventService

    EventService().publish(
        actor=actor,
        event_type=f"med_finance.payment_{suffix}",
        record_id=row.pk,
        data=(("charge", str(row.charge_id)), ("method", row.method), ("amount", row.amount), ("status", row.status)),
    )


def _has_live_receipt(payment: Payment) -> bool:
    """Whether the payment has a receipt that was not voided (none until receipts exist)."""
    return False


def _issue_receipt(actor: Any, payment: Payment, *, key: str) -> None:
    """Issue the receipt of a payment (nothing until receipts exist)."""
    return None


def _clean_payer(name: object, document: object) -> tuple[str, str]:
    from .validators import digits, valid_tax_id

    if not isinstance(name, str) or len(name) > 200:
        raise InvalidInput({"payer_name": [gettext("Use até 200 caracteres.")]})
    clean = digits(document)
    if not valid_tax_id(clean):
        raise InvalidInput({"payer_document": [gettext("Informe um CPF ou CNPJ válido.")]})
    return name.strip(), clean


def _item_rows(actor: Any, charge: Charge, desk: CashDesk, items: object) -> list[ChargeItem]:
    from skeleton.access.policies import authorized_queryset

    if not isinstance(items, tuple) or not 1 <= len(items) <= 50:
        raise InvalidInput({"items": [gettext("Informe de 1 a 50 itens.")]})
    rows = []
    for item in items:
        if not isinstance(item, ChargeItemInput):
            raise InvalidInput({"items": [gettext("Use ChargeItemInput.")]})
        if type(item.quantity) is not int or not 1 <= item.quantity <= 1000:
            raise InvalidInput({"quantity": [gettext("Use uma quantidade de 1 a 1000.")]})
        price = None
        if item.code:
            if desk.price_list_id is None:
                raise InvalidInput({"code": [gettext("O caixa não tem tabela de preços.")]})
            price = (
                authorized_queryset(PriceItem, user=actor, action="read")
                .filter(price_list_id=desk.price_list_id, code=item.code, is_active=True)
                .first()
            )
            if price is None and item.unit_amount is None:
                raise InvalidInput({"code": [gettext("Código sem preço ativo na tabela do caixa.")]})
        unit = _amount(item.unit_amount if item.unit_amount is not None else price.amount, "unit_amount")
        discount = _amount(item.discount_amount, "discount_amount")
        if discount > unit * item.quantity:
            raise InvalidInput({"discount_amount": [gettext("O desconto passa o valor do item.")]})
        description = (item.description or (price.description if price else "")).strip()
        if not description or len(description) > 200:
            raise InvalidInput({"description": [gettext("Informe a descrição do item (até 200 caracteres).")]})
        rows.append(
            ChargeItem(
                organization_id=charge.organization_id,
                charge=charge,
                price_item=price,
                code=item.code[:40],
                description=description,
                quantity=item.quantity,
                unit_amount=unit,
                discount_amount=discount,
                total=unit * item.quantity - discount,
            )
        )
    return rows


def _recalculate(charge: Charge) -> None:
    from django.db.models import Sum

    total = ChargeItem.objects.filter(charge=charge).aggregate(total=Sum("total"))["total"] or 0
    if total > MAX_AMOUNT:
        raise InvalidInput({"items": [gettext("O total passa o limite.")]})
    charge.total = total
    charge.save(update_fields={"total"})


def _confirm(actor: Any, charge: Charge) -> None:
    from . import ledger_bridge

    if charge.total <= 0:
        raise InvalidInput({"items": [gettext("A conta precisa de um total maior que zero.")]})
    with _ledger_errors():
        charge.ledger_title = ledger_bridge.create_title(
            actor,
            charge=charge,
            desk=charge.desk,
            description=gettext("Conta %(code)s") % {"code": charge.code},
            idempotency_key=f"med_finance:charge:{charge.pk}",
        )
    charge.status = Charge.Status.OPEN
    charge.confirmed_at = timezone.now()
    charge.save(update_fields={"ledger_title", "status", "confirmed_at"})
    _publish_charge(actor, "confirmed", charge)


def _charge(actor: Any, charge_id: object, *, write: bool = False, lock: bool = False) -> Charge:
    return common.row(actor, Charge, charge_id, field="charge_id", write=write, lock=lock)


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


def _charge_detail(actor: Any, charge: Charge) -> ChargeDetail:
    from skeleton.access.policies import authorized_queryset

    items = authorized_queryset(ChargeItem, user=actor, action="read").filter(charge=charge)
    return ChargeDetail(
        charge_info(charge),
        tuple(charge_item_info(row) for row in items.order_by("created_at", "sysid")),
        charge.desk_id in _writable_ids(actor, CashDesk),
    )


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

    # ------------------------------------------------------------------ cash sessions

    @service_method(read_only=True, since="0.1.0")
    def current_session(self, *, actor: Any, desk_id: UUID | None = None) -> SessionInfo | None:
        """The open session of a cash desk (the default one when not informed), or ``None``.

        Autorização: leitura do caixa.
        Erros: NotFound para caixa ilegível ou sem caixa padrão.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        desk = _default(actor, CashDesk, desk_id, field="desk_id")
        row = authorized_queryset(CashSession, user=actor, action="read").filter(desk=desk, status="open").first()
        return session_info(row) if row is not None else None

    @service_method(read_only=False, since="0.1.0")
    def open_session(
        self, *, actor: Any, desk_id: UUID | None = None, opening_amount: int = 0, idempotency_key: str
    ) -> SessionInfo:
        """Open a session of the cash desk with the cash in the drawer.

        Autorização: alteração no caixa.
        Erros: NotFound; Forbidden; InvalidInput para valor inválido; Conflict("session_already_open").
        Efeitos: grava a sessão aberta. A mesma chave devolve a já aberta.
        """
        from django.db import IntegrityError, transaction

        from skeleton.access.policies import require_parent_action

        key = common.key(idempotency_key)
        amount = _amount(opening_amount, "opening_amount")
        sysid = common.deterministic_id("session", actor, key)
        existing = CashSession.objects.filter(pk=sysid).first()
        if existing is not None:
            return session_info(existing)
        desk = _default(actor, CashDesk, desk_id, field="desk_id", write=True)
        require_parent_action(CashSession, desk, user=actor, action="create")
        if CashSession.objects.filter(desk=desk, status="open").exists():
            raise Conflict("session_already_open", gettext("Este caixa já tem uma sessão aberta."))
        row = CashSession(
            sysid=sysid,
            organization_id=desk.organization_id,
            desk=desk,
            opened_by_id=actor.pk,
            opened_at=timezone.now(),
            opening_amount=amount,
        )
        try:
            with transaction.atomic():
                row.save()
        except IntegrityError:
            raise Conflict("session_already_open", gettext("Este caixa já tem uma sessão aberta.")) from None
        return session_info(row)

    @service_method(read_only=False, since="0.1.0")
    def add_movement(
        self, *, actor: Any, session_id: UUID, kind: str, amount: int, reason: str, idempotency_key: str
    ) -> MovementInfo:
        """Record a supply or a withdrawal of cash in an open session and post it to the ledger.

        Autorização: alteração no caixa.
        Erros: NotFound; Forbidden; InvalidInput para tipo, valor ou motivo inválidos;
        Conflict("session_closed"); Conflict("insufficient_cash") para sangria maior que o dinheiro
        esperado; Conflict("ledger_rejected") quando o livro recusa (período travado, chave sem conta).
        Efeitos: grava o movimento e o lançamento no livro (regra ``med_finance.cash_supply`` ou
        ``cash_withdrawal``). A mesma chave devolve o já gravado.
        """
        from skeleton.access.policies import require_parent_action

        from . import ledger_bridge

        key = common.key(idempotency_key)
        if kind not in CashMovement.Kind.values:
            raise InvalidInput({"kind": [gettext("Use suprimento ou sangria.")]})
        value = _amount(amount, positive=True)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise InvalidInput({"reason": [gettext("Informe o motivo (até 200 caracteres).")]})
        sysid = common.deterministic_id("movement", actor, key)
        existing = CashMovement.objects.filter(pk=sysid).first()
        if existing is not None:
            return movement_info(existing)
        session = common.row(actor, CashSession, session_id, field="session_id", write=True, lock=True)
        if session.status != CashSession.Status.OPEN:
            raise Conflict("session_closed", gettext("A sessão do caixa está fechada."))
        if kind == CashMovement.Kind.WITHDRAWAL and value > _expected_cash(session):
            raise Conflict("insufficient_cash", gettext("A sangria é maior que o dinheiro esperado no caixa."))
        require_parent_action(CashMovement, session, user=actor, action="create")
        row = CashMovement(
            sysid=sysid,
            organization_id=session.organization_id,
            session=session,
            kind=kind,
            amount=value,
            reason=reason.strip(),
            at=timezone.now(),
        )
        row.save()
        with _ledger_errors():
            row.ledger_entry = ledger_bridge.post_movement(
                actor, movement=row, desk=session.desk, idempotency_key=f"med_finance:movement:{row.pk}"
            )
        row.save(update_fields={"ledger_entry"})
        return movement_info(row)

    @service_method(read_only=False, since="0.1.0")
    def close_session(
        self, *, actor: Any, session_id: UUID, counted_amount: int, expected_revision: int, note: str = ""
    ) -> SessionInfo:
        """Close a session with the counted cash; the difference to the expected cash is recorded.

        Autorização: alteração no caixa, e ser quem abriu a sessão ou ter a gestão de acesso do caixa.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("session_closed") ou Conflict("stale_revision").
        Efeitos: grava valor contado, esperado e diferença; a sessão fechada não recebe pagamento nem movimento.
        """
        from django.core.exceptions import PermissionDenied

        from skeleton.access.policies import authorized_queryset

        counted = _amount(counted_amount, "counted_amount")
        if not isinstance(note, str) or len(note) > 300:
            raise InvalidInput({"note": [gettext("Use até 300 caracteres.")]})
        session = common.row(actor, CashSession, session_id, field="session_id", write=True, lock=True)
        common.check_revision(session, expected_revision)
        if session.status != CashSession.Status.OPEN:
            raise Conflict("session_closed", gettext("A sessão do caixa já está fechada."))
        if session.opened_by_id != actor.pk:
            try:
                manages = (
                    authorized_queryset(CashDesk, user=actor, action="manage_access")
                    .filter(pk=session.desk_id)
                    .exists()
                )
            except PermissionDenied:
                manages = False
            if not manages:
                raise Forbidden(gettext("Fecha o caixa quem o abriu ou quem gere o acesso dele."))
        expected = _expected_cash(session)
        common.apply_changes(
            session,
            {
                "status": CashSession.Status.CLOSED,
                "closed_by_id": actor.pk,
                "closed_at": timezone.now(),
                "counted_amount": counted,
                "expected_amount": expected,
                "difference": counted - expected,
                "note": note.strip(),
            },
        )
        return session_info(session)

    @service_method(read_only=True, since="0.1.0")
    def session_report(self, *, actor: Any, session_id: UUID) -> SessionReport:
        """Totals of a session: by payment method, supplies, withdrawals and the expected cash.

        Autorização: leitura do caixa.
        Erros: NotFound para sessão ilegível.
        Efeitos: nenhum.
        """
        from django.db.models import Sum

        from skeleton.access.policies import authorized_queryset

        session = common.row(actor, CashSession, session_id, field="session_id", write=False)
        movements = authorized_queryset(CashMovement, user=actor, action="read").filter(session=session)
        totals = {row["kind"]: row["total"] for row in movements.values("kind").annotate(total=Sum("amount"))}
        return SessionReport(
            session_info(session),
            _payments_by_method(actor, session),
            totals.get("supply", 0) or 0,
            totals.get("withdrawal", 0) or 0,
            _expected_cash(session),
            tuple(movement_info(row) for row in movements.order_by("at", "sysid")),
        )

    @service_method(read_only=True, since="0.1.0")
    def sessions(
        self,
        *,
        actor: Any,
        desk_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[SessionInfo]:
        """Sessions of a cash desk, newest first.

        Autorização: leitura do caixa.
        Erros: NotFound; InvalidInput para datas sem fuso, cursor ou tamanho inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        desk = _default(actor, CashDesk, desk_id, field="desk_id")
        rows = authorized_queryset(CashSession, user=actor, action="read").filter(desk=desk)
        for value, name, lookup in ((start, "start", "opened_at__gte"), (end, "end", "opened_at__lt")):
            if value is not None:
                if not isinstance(value, datetime) or value.tzinfo is None:
                    raise InvalidInput({name: [gettext("Informe data e hora com fuso.")]})
                rows = rows.filter(**{lookup: value})
        return paginate(
            rows.order_by("-opened_at", "-sysid"),
            convert=session_info,
            cursor=cursor,
            page_size=page_size,
            key=("-opened_at", "-sysid"),
        )

    # ------------------------------------------------------------------ charges

    @service_method(read_only=False, since="0.1.0")
    def create_charge(
        self,
        *,
        actor: Any,
        patient_id: UUID,
        items: tuple[ChargeItemInput, ...],
        desk_id: UUID | None = None,
        due_date: date | None = None,
        payer_name: str = "",
        payer_document: str = "",
        appointment_id: UUID | None = None,
        origin_app: str = "",
        origin_key: str = "",
        confirm: bool = True,
        note: str = "",
        idempotency_key: str,
    ) -> ChargeDetail:
        """Create a charge of the patient at a desk; confirmed (the default), it becomes a receivable title.

        With ``origin_app`` (a registered charge origin) and ``origin_key``, the same origin returns
        the same charge.
        Autorização: alteração no caixa e leitura do paciente (e da consulta, quando informada).
        Erros: NotFound; Forbidden; InvalidInput para itens, valores, pagador, origem não registrada,
        consulta de outro paciente ou total zero ao confirmar; Conflict("ledger_rejected").
        Efeitos: grava a conta e os itens; ao confirmar, cria o título no livro (sem nome nem
        documento do paciente, só ``party_ref``) e publica ``charge_confirmed``. A mesma chave
        devolve a já criada.
        """
        from applications.med_patients.service_api import PatientService
        from skeleton.access.policies import require_parent_action
        from skeleton.service_api.sequences import SequenceService

        from .extension import charge_origin
        from .registration import CHARGE_SEQUENCE

        key = common.key(idempotency_key)
        if origin_app or origin_key:
            if charge_origin(origin_app) is None:
                raise InvalidInput({"origin_app": [gettext("Origem de conta não registrada.")]})
            if not isinstance(origin_key, str) or not 1 <= len(origin_key) <= 80:
                raise InvalidInput({"origin_key": [gettext("Informe a chave da origem (até 80 caracteres).")]})
            existing = Charge.objects.filter(origin_app=origin_app, origin_key=origin_key).first()
            if existing is not None:
                return _charge_detail(actor, existing)
        sysid = common.deterministic_id("charge", actor, key)
        existing = Charge.objects.filter(pk=sysid).first()
        if existing is not None:
            return _charge_detail(actor, existing)
        name, document = _clean_payer(payer_name, payer_document)
        if not isinstance(note, str) or len(note) > 300:
            raise InvalidInput({"note": [gettext("Use até 300 caracteres.")]})
        if due_date is not None and not isinstance(due_date, date):
            raise InvalidInput({"due_date": [gettext("Informe uma data.")]})
        desk = _default(actor, CashDesk, desk_id, field="desk_id", write=True)
        require_parent_action(Charge, desk, user=actor, action="create")
        patient = PatientService().summary(actor=actor, patient_id=as_uuid(patient_id, field="patient_id"))
        appointment = None
        if appointment_id is not None:
            from applications.med_scheduling.service_api import SchedulingService

            appointment = (
                SchedulingService()
                .appointment(actor=actor, appointment_id=as_uuid(appointment_id, field="appointment_id"))
                .appointment
            )
            if appointment.patient_id != patient.sysid:
                raise InvalidInput({"appointment_id": [gettext("A consulta é de outro paciente.")]})
        number = SequenceService().next_number(actor=actor, key=CHARGE_SEQUENCE)
        charge = Charge(
            sysid=sysid,
            organization_id=desk.organization_id,
            desk=desk,
            code=number.formatted,
            patient_id=patient.sysid,
            payer_name=name,
            payer_document=document,
            due_date=due_date or timezone.localdate(),
            origin_app=origin_app,
            origin_key=origin_key,
            appointment_id=appointment.sysid if appointment else None,
            note=note.strip(),
        )
        charge.save()
        for row in _item_rows(actor, charge, desk, items):
            row.save()
        _recalculate(charge)
        if confirm:
            _confirm(actor, charge)
        return _charge_detail(actor, charge)

    @service_method(read_only=False, since="0.1.0")
    def add_item(self, *, actor: Any, charge_id: UUID, item: ChargeItemInput, expected_revision: int) -> ChargeDetail:
        """Add a line to a draft charge, with CAS on the charge.

        Autorização: alteração no caixa.
        Erros: NotFound; Forbidden; InvalidInput; Conflict("not_draft") ou Conflict("stale_revision").
        Efeitos: grava o item e recalcula o total.
        """
        charge = _charge(actor, charge_id, write=True, lock=True)
        common.check_revision(charge, expected_revision)
        if charge.status != Charge.Status.DRAFT:
            raise Conflict("not_draft", gettext("Só a conta em rascunho muda de itens."))
        for row in _item_rows(actor, charge, charge.desk, (item,)):
            row.save()
        _recalculate(charge)
        return _charge_detail(actor, charge)

    @service_method(read_only=False, since="0.1.0")
    def remove_item(self, *, actor: Any, charge_id: UUID, item_id: UUID, expected_revision: int) -> ChargeDetail:
        """Remove a line of a draft charge, with CAS on the charge.

        Autorização: alteração no caixa.
        Erros: NotFound; Forbidden; Conflict("not_draft") ou Conflict("stale_revision").
        Efeitos: exclusão lógica do item e novo total.
        """
        charge = _charge(actor, charge_id, write=True, lock=True)
        common.check_revision(charge, expected_revision)
        if charge.status != Charge.Status.DRAFT:
            raise Conflict("not_draft", gettext("Só a conta em rascunho muda de itens."))
        row = ChargeItem.objects.filter(charge=charge, pk=as_uuid(item_id, field="item_id")).first()
        if row is None:
            raise NotFound()
        row.delete()
        _recalculate(charge)
        return _charge_detail(actor, charge)

    @service_method(read_only=False, since="0.1.0")
    def confirm_charge(self, *, actor: Any, charge_id: UUID, expected_revision: int) -> ChargeDetail:
        """Confirm a draft charge: its items freeze and it becomes a receivable title in the ledger.

        Autorização: alteração no caixa (e, pelo livro, alteração na conta, que é a origem do título).
        Erros: NotFound; Forbidden; InvalidInput para total zero; Conflict("not_draft"),
        Conflict("stale_revision") ou Conflict("ledger_rejected").
        Efeitos: cria o título, grava a situação "em aberto" e publica ``charge_confirmed``.
        """
        charge = _charge(actor, charge_id, write=True, lock=True)
        common.check_revision(charge, expected_revision)
        if charge.status != Charge.Status.DRAFT:
            raise Conflict("not_draft", gettext("A conta já foi confirmada ou cancelada."))
        _confirm(actor, charge)
        return _charge_detail(actor, charge)

    @service_method(read_only=False, since="0.1.0")
    def cancel_charge(self, *, actor: Any, charge_id: UUID, reason: str, expected_revision: int) -> ChargeDetail:
        """Cancel a charge without registered payments (reverse them first); its title is cancelled.

        Autorização: alteração no caixa.
        Erros: NotFound; Forbidden; InvalidInput sem motivo; Conflict("has_payments"),
        Conflict("cancelled"), Conflict("stale_revision") ou Conflict("ledger_rejected").
        Efeitos: grava a situação e o motivo, cancela o título no livro e publica ``charge_cancelled``.
        """
        from . import ledger_bridge

        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise InvalidInput({"reason": [gettext("Informe o motivo (até 200 caracteres).")]})
        charge = _charge(actor, charge_id, write=True, lock=True)
        common.check_revision(charge, expected_revision)
        if charge.status in (Charge.Status.CANCELLED, Charge.Status.PAID):
            raise Conflict("cancelled", gettext("A conta já foi cancelada ou paga."))
        if _has_active_payments(charge):
            raise Conflict("has_payments", gettext("Estorne os pagamentos antes de cancelar a conta."))
        if charge.ledger_title:
            with _ledger_errors():
                ledger_bridge.cancel_title(actor, title_id=charge.ledger_title, reason=reason.strip())
        common.apply_changes(
            charge,
            {"status": Charge.Status.CANCELLED, "cancelled_at": timezone.now(), "cancel_reason": reason.strip()},
        )
        _publish_charge(actor, "cancelled", charge)
        return _charge_detail(actor, charge)

    @service_method(read_only=True, since="0.1.0")
    def charge(self, *, actor: Any, charge_id: UUID) -> ChargeDetail:
        """One charge with its items.

        Autorização: leitura do caixa.
        Erros: NotFound para conta inexistente, de outra organização ou ilegível.
        Efeitos: nenhum.
        """
        return _charge_detail(actor, _charge(actor, charge_id))

    @service_method(read_only=True, since="0.1.0")
    def charges(
        self,
        *,
        actor: Any,
        patient_id: UUID | None = None,
        status: str | None = None,
        desk_id: UUID | None = None,
        start: date | None = None,
        end: date | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[ChargeInfo]:
        """Charges of the desks the actor reads, newest first, filtered by patient, status, desk or due date.

        Autorização: leitura de cada caixa.
        Erros: InvalidInput para situação, datas, cursor ou tamanho inválidos.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Charge, user=actor, action="read")
        if patient_id is not None:
            rows = rows.filter(patient_id=as_uuid(patient_id, field="patient_id"))
        if desk_id is not None:
            rows = rows.filter(desk_id=as_uuid(desk_id, field="desk_id"))
        if status is not None:
            if status not in Charge.Status.values:
                raise InvalidInput({"status": [gettext("Situação desconhecida.")]})
            rows = rows.filter(status=status)
        for value, name, lookup in ((start, "start", "due_date__gte"), (end, "end", "due_date__lte")):
            if value is not None:
                if not isinstance(value, date):
                    raise InvalidInput({name: [gettext("Informe uma data.")]})
                rows = rows.filter(**{lookup: value})
        return paginate(
            rows.order_by("-created_at", "-sysid"),
            convert=charge_info,
            cursor=cursor,
            page_size=page_size,
            key=("-created_at", "-sysid"),
        )

    @service_method(read_only=True, since="0.1.0")
    def charges_for_origin(self, *, actor: Any, origin_app: str, origin_key: str) -> tuple[ChargeInfo, ...]:
        """The charge another app created for one of its records (an appointment, for example).

        Autorização: leitura do caixa.
        Erros: nenhum além do contrato.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Charge, user=actor, action="read").filter(
            origin_app=str(origin_app), origin_key=str(origin_key)
        )
        return tuple(charge_info(row) for row in rows[:10])

    @service_method(read_only=True, since="0.1.0")
    def patient_balance(self, *, actor: Any, patient_id: UUID) -> int:
        """What the patient still owes in the open and partially paid charges the actor reads (centavos).

        Autorização: leitura de cada caixa.
        Erros: InvalidInput para identificador inválido.
        Efeitos: nenhum.
        """
        from django.db.models import F, Sum

        from skeleton.access.policies import authorized_queryset

        rows = authorized_queryset(Charge, user=actor, action="read").filter(
            patient_id=as_uuid(patient_id, field="patient_id"), status__in=("open", "partially_paid")
        )
        return int(rows.aggregate(total=Sum(F("total") - F("paid_total")))["total"] or 0)

    # ------------------------------------------------------------------ payments

    @service_method(read_only=False, since="0.1.0")
    def register_payment(
        self,
        *,
        actor: Any,
        charge_id: UUID,
        method: str,
        amount: int,
        expected_revision: int,
        idempotency_key: str,
        installments: int = 1,
        authorization_code: str = "",
        issue_receipt: bool = True,
    ) -> PaymentInfo:
        """Receive a payment of a charge in the open session of its desk and settle the title in the ledger.

        Autorização: alteração no caixa da conta.
        Erros: NotFound; Forbidden; InvalidInput para forma, valor acima do saldo, parcelas (mais de
        uma só no crédito) ou código de autorização inválidos; Conflict("not_open") para conta em
        rascunho, paga ou cancelada; Conflict("no_open_session"); Conflict("stale_revision") com a
        revisão da conta; Conflict("ledger_rejected").
        Efeitos: grava o pagamento, a baixa no livro, o total pago e a situação da conta; publica
        ``payment_registered`` e, ao quitar, ``charge_paid``; com ``issue_receipt``, emite o recibo
        na mesma transação. A mesma chave devolve o já registrado.
        """
        from skeleton.access.policies import require_parent_action

        from . import ledger_bridge

        key = common.key(idempotency_key)
        if method not in Payment.Method.values:
            raise InvalidInput({"method": [gettext("Forma de pagamento desconhecida.")]})
        value = _amount(amount, positive=True)
        if type(installments) is not int or not 1 <= installments <= 24:
            raise InvalidInput({"installments": [gettext("Use de 1 a 24 parcelas.")]})
        if installments > 1 and method != Payment.Method.CREDIT_CARD:
            raise InvalidInput({"installments": [gettext("Só o cartão de crédito é parcelado.")]})
        if not isinstance(authorization_code, str) or len(authorization_code) > 40:
            raise InvalidInput({"authorization_code": [gettext("Use até 40 caracteres.")]})
        sysid = common.deterministic_id("payment", actor, key)
        existing = Payment.objects.filter(pk=sysid).first()
        if existing is not None:
            return payment_info(existing)
        charge = _charge(actor, charge_id, write=True, lock=True)
        common.check_revision(charge, expected_revision)
        if charge.status not in (Charge.Status.OPEN, Charge.Status.PARTIALLY_PAID):
            raise Conflict("not_open", gettext("Só uma conta em aberto recebe pagamento."))
        if value > charge.total - charge.paid_total:
            raise InvalidInput({"amount": [gettext("O valor passa o saldo da conta.")]})
        session = CashSession.objects.filter(desk_id=charge.desk_id, status="open").select_for_update().first()
        if session is None:
            raise Conflict("no_open_session", gettext("Abra o caixa antes de receber."))
        require_parent_action(Payment, charge, user=actor, action="create")
        payment = Payment(
            sysid=sysid,
            organization_id=charge.organization_id,
            charge=charge,
            session=session,
            method=method,
            amount=value,
            received_at=timezone.now(),
            installments=installments,
            authorization_code=authorization_code.strip(),
            received_by_id=actor.pk,
        )
        payment.save()
        with _ledger_errors():
            payment.ledger_settlement = ledger_bridge.settle(
                actor,
                title_id=charge.ledger_title,
                desk=charge.desk,
                method=method,
                amount=value,
                on=timezone.localdate(),
                idempotency_key=f"med_finance:payment:{payment.pk}",
            )
        payment.save(update_fields={"ledger_settlement"})
        charge.paid_total += value
        charge.status = Charge.Status.PAID if charge.paid_total == charge.total else Charge.Status.PARTIALLY_PAID
        charge.save(update_fields={"paid_total", "status"})
        _publish_payment(actor, "registered", payment)
        if charge.status == Charge.Status.PAID:
            _publish_charge(actor, "paid", charge)
        if issue_receipt:
            _issue_receipt(actor, payment, key=f"payment-{payment.pk}")
        return payment_info(payment)

    @service_method(read_only=False, since="0.1.0")
    def reverse_payment(self, *, actor: Any, payment_id: UUID, reason: str, expected_revision: int) -> PaymentInfo:
        """Reverse a payment: the settlement is reversed in the ledger and the charge is open again.

        Autorização: alteração no caixa da conta.
        Erros: NotFound; Forbidden; InvalidInput sem motivo; Conflict("reversed"),
        Conflict("receipt_not_voided") com recibo vivo, Conflict("stale_revision") com a revisão do
        pagamento, Conflict("ledger_rejected").
        Efeitos: grava o estorno, estorna a baixa, recalcula a conta e publica ``payment_reversed``.
        Um estorno de sessão já fechada não muda o esperado gravado no fechamento.
        """
        from . import ledger_bridge

        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise InvalidInput({"reason": [gettext("Informe o motivo (até 200 caracteres).")]})
        payment = common.row(actor, Payment, payment_id, field="payment_id", write=True, lock=True)
        common.check_revision(payment, expected_revision)
        if payment.status != Payment.Status.REGISTERED:
            raise Conflict("reversed", gettext("O pagamento já foi estornado."))
        if _has_live_receipt(payment):
            raise Conflict("receipt_not_voided", gettext("Anule o recibo antes de estornar o pagamento."))
        charge = Charge.objects.select_for_update().get(pk=payment.charge_id)
        with _ledger_errors():
            ledger_bridge.reverse_settlement(
                actor,
                title_id=charge.ledger_title,
                settlement_id=payment.ledger_settlement,
                on=timezone.localdate(),
                reason=reason.strip(),
            )
        common.apply_changes(
            payment,
            {"status": Payment.Status.REVERSED, "reversed_at": timezone.now(), "reverse_reason": reason.strip()},
        )
        charge.paid_total -= payment.amount
        charge.status = Charge.Status.PARTIALLY_PAID if charge.paid_total else Charge.Status.OPEN
        charge.save(update_fields={"paid_total", "status"})
        _publish_payment(actor, "reversed", payment)
        return payment_info(payment)

    @service_method(read_only=True, since="0.1.0")
    def payments(self, *, actor: Any, charge_id: UUID) -> tuple[PaymentInfo, ...]:
        """The payments of a charge, oldest first.

        Autorização: leitura do caixa.
        Erros: NotFound para conta ilegível.
        Efeitos: nenhum.
        """
        from skeleton.access.policies import authorized_queryset

        charge = _charge(actor, charge_id)
        rows = authorized_queryset(Payment, user=actor, action="read").filter(charge=charge)
        return tuple(payment_info(row) for row in rows.order_by("received_at", "sysid"))
