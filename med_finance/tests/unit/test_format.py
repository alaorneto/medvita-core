"""The display filters of the finance app (no database): amounts, labels and the tone of each state (#121, #122)."""

import pytest
from django.template import Context, Template

from ...models import CashSession, Charge, Payment
from ...templatetags.med_finance_format import (
    LABELS,
    STATE_TONE_CODE,
    TONES,
    brl,
    finance_label,
    finance_marker,
    finance_state,
)

NBSP = "\u00a0"


def render(source, **context):
    return Template("{% load med_finance_format skeleton_format %}" + source).render(Context(context))


def badge_tone(code):
    """The tone the core gives a state code: badge-<tone> of status_badge."""
    return render("{{ code|status_badge }}", code=code).split("badge-")[1].split(" ")[0]


def marker_tone(code):
    return render("{{ code|marker }}", code=code).split("badge-")[1].split('"')[0]


@pytest.mark.parametrize(
    ("centavos", "text"),
    [(0, "R$ 0,00"), (5, "R$ 0,05"), (25000, "R$ 250,00"), (123456789, "R$ 1.234.567,89"), (-1000, "-R$ 10,00")],
)
def test_brl_keeps_the_sign_and_the_number_together(centavos, text):
    assert brl(centavos) == text.replace(" ", NBSP)


def test_brl_of_nothing_is_a_dash():
    assert brl(None) == brl("") == "—"


def test_every_state_has_a_tone_and_a_label():
    domains = {"charge_status": Charge.Status, "session_status": CashSession.Status, "payment_status": Payment.Status}
    for kind, choices in domains.items():
        for value, label in choices.choices:
            assert (kind, value) in TONES
            assert finance_label(value, kind) == str(label)


@pytest.mark.parametrize(
    ("kind", "value", "tone"),
    [
        ("charge_status", "draft", "neutral"),
        ("charge_status", "open", "warning"),
        ("charge_status", "partially_paid", "warning"),
        ("charge_status", "paid", "success"),
        ("charge_status", "cancelled", "neutral"),
        ("session_status", "open", "brand"),
        ("session_status", "closed", "neutral"),
        ("payment_status", "registered", "success"),
        ("payment_status", "reversed", "neutral"),
        ("price_status", "active", "success"),
        ("price_status", "inactive", "neutral"),
        ("receipt_status", "voided", "neutral"),
    ],
)
def test_state_uses_a_core_code_of_the_same_tone(kind, value, tone):
    code = finance_state(value, kind)
    assert code == STATE_TONE_CODE[tone] and badge_tone(code) == tone


def test_unknown_state_is_neutral():
    assert badge_tone(finance_state("whatever", "charge_status")) == "neutral"


def test_marker_uses_a_core_code_of_the_same_tone():
    for tone in ("brand", "warning", "neutral"):
        assert marker_tone(finance_marker(tone)) == tone
    assert marker_tone(finance_marker("unknown")) == "neutral"


def test_badge_shows_the_finance_label():
    html = render(
        '{% with label=code|finance_label:"charge_status" %}'
        '{{ code|finance_state:"charge_status"|status_badge:label }}{% endwith %}',
        code="paid",
    )
    assert html == '<span class="badge badge-success badge-dot">Paga</span>'


def test_aging_buckets_have_labels():
    assert set(LABELS["aging"]) == {"current", "1-30", "31-60", "61-90", "90+"}
    assert finance_label("1-30", "aging") == "1–30 dias"
    assert finance_label("90+", "aging") == "Mais de 90 dias"
    assert finance_label("other", "nowhere") == "other"
