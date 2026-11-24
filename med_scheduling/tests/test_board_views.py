"""The day as a board of hours (#135) and the page of a schedule in sub-tabs (#138), through the pages."""

import re
from datetime import UTC, date, datetime, time, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client
from django.urls import reverse

from ..service_api import AvailabilityRuleInput, SchedulingService
from .booking import SP, at, book, prepare

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
UNSAFE = re.compile(r"\sstyle=|\son[a-z]+=", re.IGNORECASE)
CSS = Path(__file__).resolve().parents[1] / "static" / "med_scheduling" / "med_scheduling.css"
ITEM = re.compile(r'<li class="board-(?P<kind>[a-z]+) br-(?P<row>\d+) bs-(?P<span>\d+)(?P<rest>[^"]*)">')


# The decorative icons before a label (#144) are left out of markup comparisons.
ICON = re.compile(r"<svg\b[^>]*>.*?</svg>", re.S)


def without_icons(html):
    return ICON.sub("", html)


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_scheduling:{name}", args=((organization or ready.org_a).pk, *args))


def safe(response):
    assert response.status_code == 200, response.status_code
    html = without_icons(response.content.decode())
    assert not INLINE_SCRIPT.search(html) and not UNSAFE.search(html)
    return html


def day_page(ready, client=None, day=None):
    client = client or client_for(ready.a.reception)
    return safe(client.get(url(ready, "day"), {"date": (day or ready.monday).isoformat()}))


def items(html):
    """The items of the board in the order of the page: kind, first row, rows, the other classes and the markup."""
    found = []
    matches = list(ITEM.finditer(html))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else html.index("</ol>", match.end())
        found.append(
            (match["kind"], int(match["row"]), int(match["span"]), match["rest"].split(), html[match.end() : end])
        )
    return found


def free_links(html):
    return [unescape(href) for href in re.findall(r'<a class="board-free-link" href="([^"]+)"', html)]


def let_finance_read(ready):
    """Finance reads the schedule and does not write it."""
    with ready.as_user(ready.a.admin) as admin:
        service = SchedulingService()
        service.set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            writer_user_ids=(),
            expected_revision=service.schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
        )
    return client_for(ready.a.finance)


def set_grid(ready, *rules):
    with ready.as_user(ready.a.reception) as actor:
        service = SchedulingService()
        revision = service.schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
        service.set_availability(actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=revision)


def block_monday(ready, start=0, end=24):
    first = datetime.combine(ready.monday, time(), tzinfo=SP)
    with ready.as_user(ready.a.reception) as actor:
        return SchedulingService().add_block(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            starts_at=first + timedelta(hours=start),
            ends_at=first + timedelta(hours=end),
            reason="vacation",
            idempotency_key=f"block-{start}-{end}",
        )


# ------------------------------------------------------------------------------------- #135 the board


def test_each_appointment_takes_the_rows_of_its_time_and_length(ready):
    appointment = book(ready, 9)
    longer = book(ready, 10, duration_minutes=60, key="long")
    html = day_page(ready)
    # The axis: 08:00 to 12:00 by 15 minutes (16 rows), one label per hour, under the row of the heads.
    assert 'class="day-board board-step-15"' in html and 'class="board-axis bs-17"' in html
    assert re.findall(r'<span class="board-hour br-(\d+) bs-4">(\d\d:00)</span>', html) == [
        ("2", "08:00"),
        ("6", "09:00"),
        ("10", "10:00"),
        ("14", "11:00"),
    ]
    board = items(html)
    placed = {
        re.search(r'href="[^"]*/appointments/([0-9a-f-]+)/"', markup).group(1): (row, span)
        for kind, row, span, _rest, markup in board
        if kind == "appointment"
    }
    assert placed == {str(appointment.sysid): (5, 2), str(longer.sysid): (9, 4)}
    # The period is the band behind them, from its start to its end.
    assert [(row, span) for kind, row, span, _rest, _markup in board if kind == "band"] == [(1, 16)]
    # The free times fill the gaps: 08:00, 08:30, 09:30 and 11:00, 11:30, each 30 minutes long.
    assert [(row, span) for kind, row, span, _rest, _markup in board if kind == "free"] == [
        (1, 2),
        (3, 2),
        (7, 2),
        (13, 2),
        (15, 2),
    ]
    # Nothing crosses: one lane.
    assert "lanes-" not in html and " bl-" not in html


def test_a_free_time_opens_the_booking_with_the_schedule_the_day_and_the_time(ready):
    client = client_for(ready.a.reception)
    html = day_page(ready, client)
    first = free_links(html)[0]
    address = urlsplit(first)
    assert address.path == url(ready, "book")
    query = {name: values[0] for name, values in parse_qs(address.query).items()}
    assert query == {
        "schedule": str(ready.schedule.sysid),
        "day": ready.monday.isoformat(),
        "slot": at(ready, 8).astimezone(UTC).isoformat(),
    }
    # Nothing personal in the address: the schedule, the day and the time only.
    assert "Maria" not in first
    # The patient is chosen on the booking page, which keeps what the link brought.
    booking = safe(client.get(f"{first}&patient={ready.patient.sysid}"))
    picked = re.search(r'<input type="radio" name="slot" value="([^"]+)"[^>]*checked', booking)
    assert picked and datetime.fromisoformat(picked.group(1)) == at(ready, 8)
    assert "Marcar consulta às 08:00" in booking
    assert re.search(rf'<option value="{ready.schedule.sysid}" selected>', booking)


def test_a_fit_in_and_a_walk_in_period_show_on_the_board(ready):
    set_grid(
        ready,
        AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),
        AvailabilityRuleInput(0, 14 * 60, 16 * 60, date(2026, 1, 1), mode="walk_in", capacity=5),
    )
    book(ready, 9)
    book(ready, 9, 15, key="fit", fit_in=True)
    html = day_page(ready)
    # The axis runs from 08:00 to 16:00, the walk-in period included.
    assert 'class="board-axis bs-33"' in html
    board = items(html)
    appointments = [(row, span, rest) for kind, row, span, rest, _markup in board if kind == "appointment"]
    assert appointments == [(5, 2, ["bl-1"]), (6, 2, ["bl-2"])]
    assert 'class="board-items lanes-2"' in html and "Encaixe" in html
    (session,) = [(row, span, markup) for kind, row, span, _rest, markup in board if kind == "session"]
    assert session[:2] == (25, 8) and "Ordem de chegada · 14:00–16:00" in session[2] and "0 de 5 vagas" in session[2]
    (offer,) = re.findall(r'href="([^"]+)">Marcar neste período', session[2])
    assert parse_qs(urlsplit(unescape(offer)).query)["slot"] == [f"walk_in:{at(ready, 14).astimezone(UTC).isoformat()}"]


def test_a_blocked_day_offers_no_free_time(ready):
    set_grid(
        ready,
        AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),
        AvailabilityRuleInput(0, 14 * 60, 16 * 60, date(2026, 1, 1), mode="walk_in"),
    )
    assert free_links(day_page(ready))
    block_monday(ready)
    html = day_page(ready)
    assert free_links(html) == [] and "Marcar neste período" not in html
    board = items(html)
    # The block shows over the periods it takes, clipped to the axis; the band says the period is blocked.
    blocks = [(row, span, markup) for kind, row, span, _rest, markup in board if kind == "block"]
    assert [item[:2] for item in blocks] == [(1, 32)] and "Bloqueio · Férias" in blocks[0][2]
    assert "Hora marcada · bloqueado" in html
    week = safe(client_for(ready.a.reception).get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday}))
    monday = week[week.index(f'datetime="{ready.monday.isoformat()}"') :]
    assert url(ready, "book") not in monday[: monday.index("</tr>")]


def test_a_period_that_ended_offers_no_free_time(ready, monkeypatch):
    late = datetime.combine(ready.monday, time(13), tzinfo=SP)
    monkeypatch.setattr("django.utils.timezone.now", lambda: late)
    html = day_page(ready)
    assert free_links(html) == [] and "Hora marcada · encerrado" in html
    (band,) = [rest for kind, _row, _span, rest, _markup in items(html) if kind == "band"]
    assert "board-ended" in band


def test_a_day_without_periods_and_who_only_reads(ready):
    tuesday = ready.monday + timedelta(days=1)
    html = day_page(ready, day=tuesday)
    assert "Sem atendimento neste dia." in html and "board-axis" not in html and "<ol" not in html
    # Who reads the schedule and does not write it sees the free times, without a link or the tools of the day.
    reader = let_finance_read(ready)
    html = day_page(ready, reader)
    assert free_links(html) == [] and html.count('class="board-free-text"') == 8
    assert "Bloquear este dia" not in html and "Alterar este dia" not in html


def test_the_board_at_both_widths(ready):
    book(ready, 9)
    html = day_page(ready)
    css = CSS.read_text(encoding="utf-8")
    # On a phone (the default rules) the board is a list per schedule; the grid is from 640 px only.
    assert re.search(r"\.day-board \{ display: flex; flex-direction: column;", css)
    assert re.search(r"\.board-axis \{ display: none; \}", css)
    wide = css[css.index("@media (min-width: 40rem) {\n  .board-scroll") :]
    assert re.search(r"\.day-board \{ display: grid;", wide) and "grid-template-rows: subgrid" in wide
    # So a phone reads each schedule in time order: the items of a column come in the order of their rows.
    rows = [row for _kind, row, _span, _rest, _markup in items(html)]
    assert rows == sorted(rows)
    # Every placement the page uses has its rule in the stylesheet, and none is written in style=.
    for name in set(re.findall(r"\b(b[rsl]-\d+)\b", html)):
        assert f".{name} {{" in css, name
    # The wide board scrolls inside its own box, never the page.
    assert re.search(r"\.board-scroll \{ overflow-x: auto;", wide)
    assert 'class="board-scroll"' in html


def test_the_free_times_of_the_week_lead_to_the_booking(ready):
    html = safe(client_for(ready.a.reception).get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday}))
    links = [unescape(href) for href in re.findall(r'<a class="slot-option" href="([^"]+)">', html)]
    assert len(links) == 8
    query = parse_qs(urlsplit(links[0]).query)
    assert query["schedule"] == [str(ready.schedule.sysid)] and query["day"] == [ready.monday.isoformat()]
    week = safe(let_finance_read(ready).get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday}))
    assert 'class="slot-option"' not in week and ">08:00</time>" in week


def test_the_board_leads_to_blocking_the_day(ready):
    html = day_page(ready)
    (address,) = re.findall(r'<a href="([^"]+)">Bloquear este dia', html)
    address = unescape(address)
    days = url(ready, "schedule-days", ready.schedule.sysid)
    assert address == f"{days}?date={ready.monday.isoformat()}#block-heading"
    page = safe(client_for(ready.a.reception).get(address.split("#")[0]))
    assert re.search(rf'name="block-day"[^>]*value="{ready.monday.isoformat()}"', page)


# ---------------------------------------------------------------------------- #138 the sub-tabs


TABS = (("schedule", "Grade"), ("schedule-days", "Dias e bloqueios"), ("schedule-types", "Tipos"))


def test_each_sub_tab_has_its_address_and_says_it_is_the_current_one(ready, subtests):
    client = client_for(ready.a.reception)
    tabs = (*TABS, ("schedule-online", "Marcação online"))
    contents = {
        "schedule": "Grade semanal",
        "schedule-days": "Dias alterados",
        "schedule-types": "Tipos atendidos nesta agenda",
        "schedule-online": "Publicar esta agenda para agendamento online",
    }
    for name, label in tabs:
        with subtests.test(tab=name):
            html = safe(client.get(url(ready, name, ready.schedule.sysid)))
            nav = re.search(r'<nav class="link-tabs schedule-tabs"[^>]*>(.*?)</nav>', html, re.S).group(1)
            current = re.findall(r'<a href="([^"]+)" aria-current="page">([^<]+)</a>', nav)
            assert current == [(url(ready, name, ready.schedule.sysid), label)]
            assert len(re.findall(r"<a href=", nav)) == 4
            assert contents[name] in html
            # Each sub-tab shows only its own part.
            assert sum(text in html for text in contents.values()) == 1
            assert f"<title>Agenda da Dra. Ana · {label} · Agendas" in html


def test_the_old_address_is_the_grid_and_takes_every_form(ready):
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)
    assert page.endswith(f"/schedules/{ready.schedule.sysid}/")
    html = safe(client.get(page))
    assert "Grade semanal" in html and 'value="periods"' in html
    # A form posted to the old address goes back to its own sub-tab.
    response = client.post(page, {"form": "block", "block-day": ready.monday.isoformat(), "block-reason": "other"})
    assert response.status_code == 302 and response["Location"] == url(ready, "schedule-days", ready.schedule.sysid)


def test_a_day_is_blocked_in_two_clicks_from_the_schedule(ready):
    client = client_for(ready.a.reception)
    days = url(ready, "schedule-days", ready.schedule.sysid)
    for name in ("schedule", "schedule-types", "schedule-online"):
        # One: "Bloquear um dia", in the header of every sub-tab, opens the form with today filled.
        html = safe(client.get(url(ready, name, ready.schedule.sysid)))
        assert f'<a class="btn btn-primary" href="{days}#block-heading">Bloquear um dia</a>' in html
    html = safe(client.get(days))
    assert 'id="block-heading"' in html and html.index('id="block-heading"') < html.index("Dias alterados")
    today = re.search(r'name="block-day"[^>]*value="([0-9-]+)"', html).group(1)
    assert not re.search(r'name="block-(start|end)"[^>]*required', html)
    # Two: "Bloquear", with the hours blank, blocks the whole day.
    response = client.post(
        days, {"form": "block", "block-day": today, "block-reason": "vacation", "idempotency_key": "two-clicks"}
    )
    assert response.status_code == 302 and response["Location"] == days
    first = datetime.combine(date.fromisoformat(today), time(), tzinfo=SP)
    with ready.as_user(ready.a.reception) as actor:
        (block,) = SchedulingService().blocks(
            actor=actor, schedule_id=ready.schedule.sysid, start=first, end=first + timedelta(days=1)
        )
    assert (block.starts_at, block.ends_at, block.reason) == (first, first + timedelta(days=1), "vacation")
    assert "Bloqueio incluído" in safe(client.get(days))


def test_a_block_with_one_hour_is_refused_on_its_sub_tab(ready):
    client = client_for(ready.a.reception)
    days = url(ready, "schedule-days", ready.schedule.sysid)
    fields = {"form": "block", "block-day": ready.monday.isoformat(), "block-reason": "other", "block-start": "08:00"}
    response = client.post(url(ready, "schedule", ready.schedule.sysid), fields)
    html = without_icons(response.content.decode())
    assert response.status_code == 400 and "deixe os dois em branco" in html
    assert re.search(rf'<a href="{days}" aria-current="page">Dias e bloqueios</a>', html)


def test_who_does_not_read_the_schedule_gets_404_on_every_sub_tab(ready, subtests):
    stranger = client_for(ready.a.finance)  # Finance does not read this schedule.
    outsider = client_for(ready.b.reception)
    for name in ("schedule", "schedule-days", "schedule-types", "schedule-online"):
        with subtests.test(tab=name):
            assert stranger.get(url(ready, name, ready.schedule.sysid)).status_code == 404
            foreign = url(ready, name, ready.schedule.sysid, organization=ready.org_b)
            assert outsider.get(foreign).status_code == 404


def test_who_only_reads_sees_the_sub_tabs_without_forms(ready, subtests):
    reader = let_finance_read(ready)
    for name in ("schedule", "schedule-days", "schedule-types", "schedule-online"):
        with subtests.test(tab=name):
            html = safe(reader.get(url(ready, name, ready.schedule.sysid)))
            assert 'name="form"' not in html and 'name="revision"' not in html and "Bloquear um dia" not in html
    days = url(ready, "schedule-days", ready.schedule.sysid)
    fields = {"form": "block", "block-day": ready.monday.isoformat(), "block-reason": "other"}
    assert reader.post(days, fields).status_code == 404


# ------------------------------------------------------------------------- #138 the settings


def practice_fields(ready, **values):
    with ready.as_user(ready.a.reception) as actor:
        practice = SchedulingService().practice(actor=actor)
    fields = {"name": practice.name, "timezone": "America/Sao_Paulo", "state": "", **values}
    return {
        "form": "practice",
        "revision": practice.revision,
        "idempotency_key": "practice",
        **{f"practice-{name}": value for name, value in fields.items()},
    }


def test_the_settings_buttons_say_what_they_save(ready):
    html = safe(client_for(ready.a.reception).get(url(ready, "settings")))
    buttons = re.findall(r'<button type="submit" class="btn btn-primary">([^<]+)</button>', html)
    assert buttons == [
        "Salvar os dados do consultório",
        "Cadastrar profissional",
        "Cadastrar sala",
        "Cadastrar tipo de atendimento",
    ]
    assert re.search(r'<select name="practice-timezone"[^>]*>', html)
    assert re.search(r'<option value="America/Sao_Paulo" selected>', html)
    assert (
        re.search(r'<select name="practice-state"[^>]*>', html) and '<option value="SP">São Paulo (SP)</option>' in html
    )
    assert re.search(r'<select name="professional-council_state"[^>]*>', html)


def test_the_time_zone_and_the_uf_are_chosen_from_the_lists(ready, subtests):
    client = client_for(ready.a.reception)
    with subtests.test("a time zone out of the list is refused and nothing changes"):
        response = client.post(url(ready, "settings"), practice_fields(ready, timezone="Europe/Lisbon"))
        assert response.status_code == 400 and 'href="#id_practice-timezone"' in without_icons(
            response.content.decode()
        )
        response = client.post(url(ready, "settings"), practice_fields(ready, state="XX"))
        assert response.status_code == 400 and 'href="#id_practice-state"' in without_icons(response.content.decode())
        with ready.as_user(ready.a.reception) as actor:
            practice = SchedulingService().practice(actor=actor)
        assert (practice.timezone, practice.state) == ("America/Sao_Paulo", "")
    with subtests.test("one of the lists is saved"):
        response = client.post(url(ready, "settings"), practice_fields(ready, timezone="America/Recife", state="PE"))
        assert response.status_code == 302
        assert "Dados do consultório salvos" in safe(client.get(url(ready, "settings")))
        with ready.as_user(ready.a.reception) as actor:
            practice = SchedulingService().practice(actor=actor)
        assert (practice.timezone, practice.state) == ("America/Recife", "PE")
