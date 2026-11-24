"""Template filters of the finance app: centavos as reais (``{{ amount|brl }}``) and labels of codes."""

from django import template
from django.utils.translation import gettext_lazy

from ..models import CashMovement, CashSession, Charge, Payment

register = template.Library()

CHOICES = {
    "charge_status": Charge.Status,
    "method": Payment.Method,
    "movement": CashMovement.Kind,
    "payment_status": Payment.Status,
    "session_status": CashSession.Status,
}
# Labels of codes that are not model choices: the aging buckets of the receivables report.
LABELS = {
    "aging": {
        "current": gettext_lazy("A vencer"),
        "1-30": gettext_lazy("1–30 dias"),
        "31-60": gettext_lazy("31–60 dias"),
        "61-90": gettext_lazy("61–90 dias"),
        "90+": gettext_lazy("Mais de 90 dias"),
    },
}

# The core's status_badge and marker read fixed maps (#121): a state or marker of this app is shown with a core code
# of the same tone and this app's own label. Tones: success concluído; brand em andamento; warning pede atenção;
# danger falhou ou é irreversível; neutral inativo, encerrado ou rascunho.
STATE_TONE_CODE = {
    "success": "completed",
    "brand": "running",
    "warning": "pending",
    "danger": "failed",
    "neutral": "withdrawn",
}
MARKER_TONE_CODE = {"brand": "primary", "warning": "locked", "neutral": "private"}
TONES = {
    ("charge_status", "draft"): "neutral",
    ("charge_status", "open"): "warning",
    ("charge_status", "partially_paid"): "warning",
    ("charge_status", "paid"): "success",
    ("charge_status", "cancelled"): "neutral",
    ("session_status", "open"): "brand",
    ("session_status", "closed"): "neutral",
    ("payment_status", "registered"): "success",
    ("payment_status", "reversed"): "neutral",
    ("price_status", "active"): "success",
    ("price_status", "inactive"): "neutral",
    ("receipt_status", "issued"): "success",
    ("receipt_status", "voided"): "neutral",
}


@register.filter
def brl(value: object) -> str:
    """``123456`` → ``R$ 1.234,56``, with a non-breaking space after the sign of the currency."""
    if value in (None, ""):
        return "—"
    amount = int(value)
    sign = "-" if amount < 0 else ""
    reais, cents = divmod(abs(amount), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


@register.filter
def finance_label(value: object, kind: str) -> str:
    """The translated label of a code of this app (``{{ charge.status|finance_label:"charge_status" }}``)."""
    choices = CHOICES.get(kind)
    labels = dict(choices.choices) if choices is not None else LABELS.get(kind)
    if labels is None:
        return str(value)
    return str(labels.get(value, value))


@register.filter
def finance_state(value: object, kind: str) -> str:
    """The core state code with this app's tone: ``{{ code|finance_state:"charge_status"|status_badge:label }}``."""
    return STATE_TONE_CODE[TONES.get((kind, str(value)), "neutral")]


@register.filter
def finance_marker(tone: object) -> str:
    """The core marker code of a tone: ``{{ "warning"|finance_marker|marker:label }}``."""
    return MARKER_TONE_CODE.get(str(tone), "private")


@register.filter
def in_words(value: object) -> str:
    from ..money_words import amount_words

    return amount_words(int(value)) if value not in (None, "") else ""
