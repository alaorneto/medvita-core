"""Literal placeholder replacement of document bodies (no database, no template engine)."""

from ...documents import BASIC_KINDS, render_placeholders

VALUES = {"patient_name": "Maria {{date}}", "date": "02/01/2026", "professional_name": "Dra. Ana"}


def test_known_markers_are_replaced_once():
    body = "{{patient_name}} em {{ date }} por {{professional_name}}"
    assert render_placeholders(body, VALUES) == "Maria {{date}} em 02/01/2026 por Dra. Ana"


def test_everything_else_stays_literal():
    body = "{{ other }} {% now 'Y' %} {{patient_name|upper}} {0} %(date)s {{"
    assert render_placeholders(body, VALUES) == body


def test_basic_kinds_render():
    assert len(BASIC_KINDS) == 5
    for kind in BASIC_KINDS:
        text = render_placeholders(str(kind.default_body), VALUES)
        assert "{{patient_name}}" not in text
