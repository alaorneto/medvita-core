"""The time zone and the UF of the practice are chosen from fixed lists (#138), and the form refuses anything else."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from ...forms import STATE_CHOICES, TIMEZONES, BlockForm, PracticeForm, ProfessionalForm, SetupForm
from ...validators import STATES

SP = ZoneInfo("America/Sao_Paulo")


def test_the_time_zones_are_the_ones_of_brazil_each_once():
    zones = [zone for zone, _label in TIMEZONES]
    assert len(zones) == len(set(zones)) == 16
    assert zones[0] == "America/Sao_Paulo"
    for zone in zones:
        assert zone.startswith("America/") and ZoneInfo(zone)  # Known to the IANA database of the server.
    assert all("UTC−" in str(label) for _zone, label in TIMEZONES)


def test_the_states_are_the_27_in_the_order_of_their_names():
    assert {code for code, _label in STATE_CHOICES} == STATES and len(STATE_CHOICES) == 27
    names = [label for _code, label in STATE_CHOICES]
    assert names[:3] == ["Acre (AC)", "Alagoas (AL)", "Amapá (AP)"]
    assert names.index("Pará (PA)") < names.index("Paraíba (PB)") < names.index("Paraná (PR)")


def practice(**values):
    return PracticeForm({"name": "Clínica", "timezone": "America/Sao_Paulo", "state": "", **values})


def test_the_practice_takes_a_time_zone_and_a_uf_of_the_lists():
    form = practice(timezone="America/Manaus", state="AM")
    assert form.is_valid(), form.errors
    assert (form.cleaned_data["timezone"], form.cleaned_data["state"]) == ("America/Manaus", "AM")
    assert practice().is_valid()  # The UF is optional.


@pytest.mark.parametrize("value", ["UTC", "Europe/Lisbon", "America/New_York", "Mars/Olympus", ""])
def test_a_time_zone_out_of_the_list_is_refused(value):
    form = practice(timezone=value)
    assert not form.is_valid() and "timezone" in form.errors


@pytest.mark.parametrize("value", ["XX", "sp", "São Paulo"])
def test_a_uf_out_of_the_list_is_refused(value):
    assert "state" in practice(state=value).errors
    professional = ProfessionalForm({"display_name": "Dra. Ana", "council": "crm", "council_state": value})
    assert "council_state" in professional.errors


def test_the_first_setup_offers_the_same_time_zones():
    assert SetupForm({"practice_name": "X", "timezone": "Asia/Tokyo"}).errors.keys() == {"timezone"}
    assert SetupForm({"practice_name": "X", "timezone": "America/Recife"}).is_valid()
    assert SetupForm().fields["timezone"].initial == "America/Sao_Paulo"


def block(**values):
    form = BlockForm({"day": "2026-06-01", "reason": "other", **values})
    form.is_valid()
    return form


def test_a_block_without_hours_takes_the_whole_day():
    form = block()
    assert form.is_valid()
    assert form.bounds(SP) == (datetime(2026, 6, 1, tzinfo=SP), datetime(2026, 6, 2, tzinfo=SP))
    hours = block(start="14:00", end="00:00")
    assert hours.bounds(SP) == (datetime(2026, 6, 1, 14, tzinfo=SP), datetime(2026, 6, 2, tzinfo=SP))
    morning = block(start="08:00", end="12:00")
    assert morning.bounds(SP) == (
        datetime.combine(date(2026, 6, 1), time(8), tzinfo=SP),
        datetime.combine(date(2026, 6, 1), time(12), tzinfo=SP),
    )


def test_a_block_with_one_hour_only_is_refused_on_the_blank_one():
    assert "end" in block(start="08:00").errors and "start" in block(end="12:00").errors
