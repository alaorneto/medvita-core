"""Template filters of the finance app: centavos as reais (``{{ amount|brl }}``) and labels of codes."""

from django import template

from ..models import CashMovement, Charge, Payment

register = template.Library()

CHOICES = {"charge_status": Charge.Status, "method": Payment.Method, "movement": CashMovement.Kind}


@register.filter
def brl(value: object) -> str:
    """``123456`` → ``R$ 1.234,56``."""
    if value in (None, ""):
        return "—"
    amount = int(value)
    sign = "-" if amount < 0 else ""
    reais, cents = divmod(abs(amount), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


@register.filter
def finance_label(value: object, kind: str) -> str:
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))


@register.filter
def in_words(value: object) -> str:
    from ..money_words import amount_words

    return amount_words(int(value)) if value not in (None, "") else ""
