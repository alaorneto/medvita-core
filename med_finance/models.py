"""Tables of the finance app (docs/spec.md, "Modelo de dados").

Two containers decide access: ``PriceList`` (a price table) and ``CashDesk`` (a point of
payment, bound to a ledger book). Every other table is derived from one of them. Money is always
an integer of the minor unit (``skeleton.common.money``), never a float.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from skeleton.common.models import OrganizationRecord, SecuredRecord


class PriceList(SecuredRecord):
    """A price table; its item codes are the ``billing_code`` of the appointment types."""

    name = models.CharField(max_length=120)
    currency = models.CharField(max_length=3, default="BRL")
    is_default = models.BooleanField(default=False)
    immutable_fields = ("currency",)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_finance_one_default_price_list",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class PriceItem(OrganizationRecord):
    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=40)
    description = models.CharField(max_length=200)
    amount = models.PositiveBigIntegerField()
    is_active = models.BooleanField(default=True)
    immutable_fields = ("price_list_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("price_list", "code"),
                condition=Q(deleted_at__isnull=True),
                name="med_finance_price_code",
                violation_error_code="unique",
            ),
        ]
        ordering = ("code", "sysid")


class CashDesk(SecuredRecord):
    """A point of payment; it posts to one ledger book and keeps the book accounts of each method."""

    name = models.CharField(max_length=120)
    book = models.ForeignKey("skeleton_ledger.Book", on_delete=models.PROTECT, related_name="+")
    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # Book accounts by payment key ("cash", "pix", "cards", "bank"), resolved at setup by who manages the book.
    payment_accounts = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    immutable_fields = ("book_id",)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_finance_one_default_desk",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class CashSession(OrganizationRecord):
    """One opening of a cash desk, from opening to closing; payments belong to an open session."""

    class Status(models.TextChoices):
        OPEN = "open", gettext_lazy("Aberto")
        CLOSED = "closed", gettext_lazy("Fechado")

    desk = models.ForeignKey(CashDesk, on_delete=models.PROTECT, related_name="+")
    opened_by = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField()
    opening_amount = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    closed_by = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    counted_amount = models.PositiveBigIntegerField(null=True, blank=True)
    expected_amount = models.BigIntegerField(null=True, blank=True)
    difference = models.BigIntegerField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    immutable_fields = ("desk_id", "opened_by_id", "opened_at", "opening_amount")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("desk",),
                condition=Q(status="open", deleted_at__isnull=True),
                name="med_finance_one_open_session",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-opened_at", "sysid")


class CashMovement(OrganizationRecord):
    """A supply (cash put in) or a withdrawal (cash taken out) of an open session; posted to the ledger."""

    class Kind(models.TextChoices):
        SUPPLY = "supply", gettext_lazy("Suprimento")
        WITHDRAWAL = "withdrawal", gettext_lazy("Sangria")

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=200)
    at = models.DateTimeField()
    ledger_entry = models.UUIDField(null=True, blank=True)
    immutable_fields = ("session_id", "kind", "amount", "reason", "at")

    class Meta(OrganizationRecord.Meta):
        ordering = ("at", "sysid")


class Charge(OrganizationRecord):
    """The patient's bill at a desk: a draft until confirmed, when it becomes a receivable title in the ledger."""

    class Status(models.TextChoices):
        DRAFT = "draft", gettext_lazy("Rascunho")
        OPEN = "open", gettext_lazy("Em aberto")
        PARTIALLY_PAID = "partially_paid", gettext_lazy("Parcialmente paga")
        PAID = "paid", gettext_lazy("Paga")
        CANCELLED = "cancelled", gettext_lazy("Cancelada")

    desk = models.ForeignKey(CashDesk, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="med_finance_charges")
    payer_name = models.CharField(max_length=200, blank=True)
    payer_document = models.CharField(max_length=14, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    total = models.PositiveBigIntegerField(default=0)
    paid_total = models.PositiveBigIntegerField(default=0)
    due_date = models.DateField()
    origin_app = models.CharField(max_length=40, blank=True)
    origin_key = models.CharField(max_length=80, blank=True)
    appointment = models.ForeignKey(
        "med_scheduling.Appointment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    ledger_title = models.UUIDField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    immutable_fields = ("desk_id", "code", "patient_id", "origin_app", "origin_key", "appointment_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(fields=("organization", "code"), name="med_finance_charge_code"),
            models.UniqueConstraint(
                fields=("organization", "origin_app", "origin_key"),
                condition=~Q(origin_key=""),
                name="med_finance_one_charge_per_origin",
                violation_error_code="unique",
            ),
            models.CheckConstraint(
                condition=Q(payer_document__regex=r"^([0-9]{11}|[0-9]{14})?$"), name="med_finance_payer_document"
            ),
        ]
        indexes = [models.Index(fields=("organization", "patient", "status"), name="med_finance_charge_patient")]
        ordering = ("-created_at", "sysid")


class ChargeItem(OrganizationRecord):
    """A line of a charge; changes only while the charge is a draft."""

    charge = models.ForeignKey(Charge, on_delete=models.PROTECT, related_name="+")
    price_item = models.ForeignKey(PriceItem, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    code = models.CharField(max_length=40, blank=True)
    description = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.PositiveBigIntegerField()
    discount_amount = models.PositiveBigIntegerField(default=0)
    total = models.PositiveBigIntegerField(default=0)
    immutable_fields = ("charge_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="med_finance_item_quantity"),
        ]
        ordering = ("created_at", "sysid")


class Payment(OrganizationRecord):
    """A payment of a charge received in an open cash session; a settlement of the title in the ledger."""

    class Method(models.TextChoices):
        CASH = "cash", gettext_lazy("Dinheiro")
        PIX = "pix", gettext_lazy("Pix")
        DEBIT_CARD = "debit_card", gettext_lazy("Cartão de débito")
        CREDIT_CARD = "credit_card", gettext_lazy("Cartão de crédito")
        BANK_TRANSFER = "bank_transfer", gettext_lazy("Transferência")
        OTHER = "other", gettext_lazy("Outro")

    class Status(models.TextChoices):
        REGISTERED = "registered", gettext_lazy("Registrado")
        REVERSED = "reversed", gettext_lazy("Estornado")

    charge = models.ForeignKey(Charge, on_delete=models.PROTECT, related_name="+")
    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="+")
    method = models.CharField(max_length=16, choices=Method.choices)
    amount = models.PositiveBigIntegerField()
    received_at = models.DateTimeField()
    installments = models.PositiveSmallIntegerField(default=1)
    authorization_code = models.CharField(max_length=40, blank=True)
    received_by = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REGISTERED)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.CharField(max_length=200, blank=True)
    ledger_settlement = models.UUIDField(null=True, blank=True)
    immutable_fields = (
        "charge_id",
        "session_id",
        "method",
        "amount",
        "received_at",
        "installments",
        "received_by_id",
    )

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(condition=Q(amount__gte=1), name="med_finance_payment_amount"),
            models.CheckConstraint(
                condition=Q(installments__gte=1, installments__lte=24), name="med_finance_payment_installments"
            ),
        ]
        ordering = ("received_at", "sysid")
