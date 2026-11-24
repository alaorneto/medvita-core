"""Forms of the finance pages: format checks only; the rules live in FinanceService.

Amounts are typed in reais with a comma ("250,00") and converted to centavos with
``skeleton.common.money.parse``; never through a float.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import CashMovement, Payment


class MoneyField(forms.CharField):
    """Reais typed with a comma or a dot, cleaned to integer centavos."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("widget", forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}))
        super().__init__(*args, **kwargs)

    def clean(self, value: Any) -> int | None:
        from skeleton.common.money import parse

        text = super().clean(value)
        if text in (None, ""):
            return None
        text = str(text).strip().replace("R$", "").replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            amount = parse(text, "BRL")
        except ValidationError:
            raise ValidationError(_("Informe um valor em reais, como 250,00.")) from None
        if amount < 0:
            raise ValidationError(_("O valor não pode ser negativo."))
        return amount


def apply_service_errors(form: forms.Form, error: Any) -> None:
    for name, messages in error.errors.items():
        field = name if name in form.fields else None
        for message in messages:
            form.add_error(field, message)


class SetupForm(forms.Form):
    desk_name = forms.CharField(label=_("Nome do caixa"), max_length=120, required=False)
    price_list_name = forms.CharField(label=_("Nome da tabela de preços"), max_length=120, required=False)
    writer_groups = forms.MultipleChoiceField(
        label=_("Grupos que recebem no caixa"), required=False, widget=forms.CheckboxSelectMultiple
    )
    reader_groups = forms.MultipleChoiceField(
        label=_("Grupos que só consultam"), required=False, widget=forms.CheckboxSelectMultiple
    )
    price_manager_groups = forms.MultipleChoiceField(
        label=_("Grupos que alteram os preços"), required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(str(group.sysid), group.name) for group in groups]
        for name in ("writer_groups", "reader_groups", "price_manager_groups"):
            self.fields[name].choices = choices


class OpenSessionForm(forms.Form):
    opening_amount = MoneyField(label=_("Dinheiro na gaveta"), required=False)


class MovementForm(forms.Form):
    kind = forms.ChoiceField(label=_("Movimento"), choices=CashMovement.Kind.choices)
    amount = MoneyField(label=_("Valor"))
    reason = forms.CharField(label=_("Motivo"), max_length=200)


class CloseSessionForm(forms.Form):
    counted_amount = MoneyField(label=_("Dinheiro contado"))
    note = forms.CharField(label=_("Observação"), max_length=300, required=False)


class ChargeForm(forms.Form):
    code = forms.ChoiceField(label=_("Item da tabela de preços"), required=False)
    description = forms.CharField(label=_("Ou descrição livre"), max_length=200, required=False)
    unit_amount = MoneyField(label=_("Valor (para a descrição livre)"), required=False)
    quantity = forms.IntegerField(label=_("Quantidade"), min_value=1, max_value=1000, initial=1)
    discount_amount = MoneyField(label=_("Desconto"), required=False)
    payer_name = forms.CharField(label=_("Pagador (vazio: o paciente)"), max_length=200, required=False)
    payer_document = forms.CharField(
        label=_("CPF ou CNPJ do pagador"),
        max_length=18,
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off", "spellcheck": "false"}),
    )

    def __init__(self, *args, prices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].choices = [
            ("", "—"),
            *((item.code, f"{item.code} · {item.description}") for item in prices),
        ]

    def clean(self):
        data = super().clean()
        if not data.get("code") and not (data.get("description") and data.get("unit_amount") is not None):
            raise ValidationError(_("Escolha um item da tabela ou informe descrição e valor."))
        return data


class PaymentForm(forms.Form):
    method = forms.ChoiceField(label=_("Forma de pagamento"), choices=Payment.Method.choices)
    amount = MoneyField(label=_("Valor"))
    installments = forms.IntegerField(label=_("Parcelas (cartão de crédito)"), min_value=1, max_value=24, initial=1)
    authorization_code = forms.CharField(
        label=_("Código de autorização"),
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )


class ReasonForm(forms.Form):
    reason = forms.CharField(label=_("Motivo"), max_length=200)


class PriceForm(forms.Form):
    code = forms.CharField(label=_("Código"), max_length=40)
    description = forms.CharField(label=_("Descrição"), max_length=200)
    amount = MoneyField(label=_("Valor"))
