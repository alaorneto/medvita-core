"""The template filters of the scheduling pages: tones of states and markers, and days written out (no database)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.template import Context, Template
from django.utils import timezone, translation

from ...forms import COLOR_LABELS, TypeForm
from ...models import COLORS, Appointment, WaitlistEntry
from ...templatetags.med_scheduling_labels import (
    STATE_TONE_CODE,
    TONES,
    scheduling_long_date,
    scheduling_marker,
    scheduling_short_weekday,
    scheduling_state,
)

DECIDED = {
    "scheduled": "neutral",
    "confirmed": "success",
    "arrived": "warning",
    "in_progress": "brand",
    "completed": "success",
    "no_show": "danger",
    "cancelled": "neutral",
}


def render(source, **values):
    """A snippet as a page renders it, with the core's public filters (status_badge, marker)."""
    return Template("{% load skeleton_format med_scheduling_labels %}" + source).render(Context(values))


@pytest.mark.parametrize(("code", "tone"), DECIDED.items())
def test_each_appointment_state_has_its_tone_and_keeps_its_label(code, tone):
    html = render('{{ code|scheduling_state:"status"|status_badge:"Rótulo da agenda" }}', code=code)
    assert html == f'<span class="badge badge-{tone} badge-dot">Rótulo da agenda</span>'


def test_every_state_code_of_the_app_has_a_tone():
    assert {code for kind, code in TONES if kind == "status"} == set(Appointment.Status.values)
    assert {code for kind, code in TONES if kind == "waitlist_status"} == set(WaitlistEntry.Status.values)
    assert scheduling_state("waiting", "waitlist_status") == "pending"


@pytest.mark.parametrize("tone", STATE_TONE_CODE)
def test_the_state_code_of_a_tone_is_a_core_code_of_that_tone(tone):
    assert f"badge-{tone} " in render('{{ code|status_badge:"x" }}', code=STATE_TONE_CODE[tone])


@pytest.mark.parametrize("tone", ["brand", "warning", "neutral"])
def test_the_marker_code_of_a_tone_is_a_core_marker_of_that_tone(tone):
    assert render('{{ tone|scheduling_marker|marker:"Encaixe" }}', tone=tone) == (
        f'<span class="badge badge-{tone}">Encaixe</span>'
    )


def test_an_unknown_state_or_tone_is_neutral():
    assert "badge-neutral" in render('{{ "nonsense"|scheduling_state:"status"|status_badge:"x" }}')
    assert scheduling_marker("nonsense") == "private"


def test_a_heading_day_is_written_out_with_a_capital():
    with translation.override("pt-br"):
        assert scheduling_long_date(date(2026, 11, 24)) == (
            '<time datetime="2026-11-24">Terça-feira, 24/11/2026</time>'
        )
        assert scheduling_long_date(date(2026, 11, 24), "inline") == (
            '<time datetime="2026-11-24">terça-feira, 24/11/2026</time>'
        )


def test_an_instant_is_the_day_of_the_active_clock():
    # 01:30 UTC on Tuesday is still Monday 22:30 in São Paulo.
    late = datetime(2026, 11, 24, 1, 30, tzinfo=UTC)
    with translation.override("pt-br"), timezone.override(ZoneInfo("America/Sao_Paulo")):
        assert scheduling_long_date(late) == '<time datetime="2026-11-23">Segunda-feira, 23/11/2026</time>'
        assert scheduling_short_weekday(late) == '<time datetime="2026-11-23">Seg 23/11</time>'


def test_a_column_head_has_the_short_weekday():
    # Django's pt-BR abbreviation of Saturday has no accent.
    with translation.override("pt-br"):
        assert scheduling_short_weekday(date(2026, 11, 28)) == '<time datetime="2026-11-28">Sab 28/11</time>'


@pytest.mark.parametrize("empty", [None, "", "2026-11-24"])
def test_an_empty_or_not_a_date_value_is_a_dash(empty):
    assert scheduling_long_date(empty) == "—" and scheduling_short_weekday(empty) == "—"


def test_the_colour_of_a_kind_is_offered_by_its_name():
    assert set(COLOR_LABELS) == set(COLORS)
    with translation.override("pt-br"):
        choices = {code: str(label) for code, label in TypeForm().fields["color"].choices}
    assert choices["blue"] == "Azul" and choices["teal"] == "Verde-azulado"
    assert all(code != label for code, label in choices.items())
