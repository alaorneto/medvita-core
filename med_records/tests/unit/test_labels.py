"""Labels, states and markers of the records pages, and the seal box (template engine only, no database)."""

from datetime import UTC, datetime

import pytest
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import translation

from ...templatetags.med_records_labels import TONES, records_label, records_marker, records_state


def render(source: str, **context) -> str:
    with translation.override("pt-br"):
        return Template("{% load skeleton_format med_records_labels %}" + source).render(Context(context))


@pytest.mark.parametrize(
    ("value", "kind", "label"),
    [
        ("severe", "allergy_severity", "Grave"),
        ("unknown", "allergy_severity", "Não informada"),
        ("refuted", "allergy_status", "Descartada"),
        ("food", "allergy_category", "Alimento"),
        ("active", "medication_status", "Em uso"),
        ("view_chart", "access_action", "Leitura do prontuário"),
        ("document", "template_kind", "Documento"),
    ],
)
def test_stored_codes_have_a_label(value, kind, label):
    with translation.override("pt-br"):
        assert records_label(value, kind) == label


def test_an_unknown_code_or_kind_stays_as_it_is():
    assert records_label("other_code", "allergy_status") == "other_code"
    assert records_label("x", "no_such_kind") == "x"


@pytest.mark.parametrize(("key", "tone"), sorted(TONES.items()))
def test_each_state_is_drawn_by_the_core_in_its_tone(key, tone):
    value, kind = key[1], key[0]
    html = render('{{ value|records_state:kind|status_badge:"Rótulo" }}', value=value, kind=kind)
    assert f"badge-{tone}" in html and "badge-dot" in html and "Rótulo" in html


def test_an_unknown_state_is_neutral():
    assert records_state("whatever", "allergy_status") == records_state("ended", "medication_status")


@pytest.mark.parametrize("tone", ["brand", "warning", "neutral"])
def test_each_marker_tone_is_drawn_by_the_core_in_its_tone(tone):
    html = render('{{ tone|records_marker|marker:"Pessoal" }}', tone=tone)
    assert f"badge-{tone}" in html and "badge-dot" not in html and "Pessoal" in html


def test_an_unknown_marker_tone_is_neutral():
    assert records_marker("danger") == records_marker("neutral")


def test_the_seal_box_has_one_paragraph_per_line_and_the_verification_code():
    with translation.override("pt-br"):
        html = render_to_string(
            "med_records/_seal.html",
            {
                "signed": True,
                "signed_at": datetime(2026, 11, 24, 15, 30, tzinfo=UTC),
                "author_name": "Dra. Ana",
                "author_council": "CRM 123",
                "digest": "abc123",
            },
        )
    assert "<br" not in html and html.count("<p>") == 3
    assert "<time datetime=" in html and "Dra. Ana (CRM 123)" in html
    assert "Código de verificação:" in html and 'translate="no">abc123<' in html


def test_the_seal_box_of_a_draft():
    with translation.override("pt-br"):
        html = render_to_string("med_records/_seal.html", {"signed": False})
    assert "Rascunho, não assinado." in html and "<time" not in html
