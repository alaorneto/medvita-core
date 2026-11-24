"""The desk flows (#129, #130, #131): the reception board, booking and rescheduling, and the appointment page."""

import re
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ..service_api import CHECK_IN_UNDO_MINUTES, AppointmentActionInfo, SchedulingService
from ..views import _waited, desk_state
from .booking import SP, at, prepare


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_scheduling:{name}", args=((organization or ready.org_a).pk, *args))


def page(client, address, **query):
    response = client.get(address, query)
    assert response.status_code == 200, response.status_code
    return response.content.decode()


def content(html):
    """The page from its heading on: the app's own part, without the shell of the core."""
    return html[html.index("<h1") :]


def row_of(ready, appointment_id, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return SchedulingService().appointment(actor=actor, appointment_id=appointment_id)


def fit_in(ready, starts_at, key):
    with ready.as_user(ready.a.reception) as actor:
        return SchedulingService().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            starts_at=starts_at,
            fit_in=True,
            idempotency_key=key,
        )


def step(ready, name, appointment):
    with ready.as_user(ready.a.reception) as actor:
        current = SchedulingService().appointment(actor=actor, appointment_id=appointment.sysid).appointment
        return getattr(SchedulingService(), name)(
            actor=actor, appointment_id=appointment.sysid, expected_revision=current.revision
        )


@pytest.fixture
def afternoon(ready, monkeypatch):
    """Today at 15:00 on the practice's clock, fixed: the reception and the service read the same clock."""
    today = timezone.localdate(timezone=SP)
    fixed = datetime.combine(today, time(15), tzinfo=SP)
    clock = SimpleNamespace(now=fixed)
    monkeypatch.setattr("django.utils.timezone.now", lambda: clock.now)
    return clock


# ------------------------------------------------------------------------ the desk state, pure


def fake(status, starts_at, *, arrived_at=None, mode="booked"):
    return SimpleNamespace(
        status=status, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30), mode=mode, arrived_at=arrived_at
    )


def test_the_wait_and_the_delay_follow_the_clock(monkeypatch):
    now = datetime(2026, 11, 24, 15, 0, tzinfo=SP)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    late = desk_state(fake("confirmed", now - timedelta(minutes=5)), now, writable=True)
    assert late["late"] and late["no_show"] and late["check_in"] and not late["confirm"]
    ahead = desk_state(fake("scheduled", now + timedelta(minutes=5)), now, writable=True)
    assert not ahead["late"] and not ahead["no_show"] and ahead["confirm"] and ahead["check_in"]
    walk_in = desk_state(fake("scheduled", now - timedelta(minutes=5), mode="walk_in"), now, writable=True)
    assert not walk_in["late"]  # A walk-in has no time to be late for.
    waiting = desk_state(
        fake("arrived", now - timedelta(hours=1), arrived_at=now - timedelta(minutes=12)), now, writable=True
    )
    assert waiting["waited"] == "há 12 min" and waiting["undo"] is False and not waiting["late"]
    fresh = desk_state(
        fake("arrived", now, arrived_at=now - timedelta(minutes=CHECK_IN_UNDO_MINUTES)), now, writable=True
    )
    assert fresh["undo"] is True
    assert desk_state(fake("arrived", now, arrived_at=now), now, writable=False)["undo"] is False
    reader = desk_state(fake("scheduled", now - timedelta(minutes=5)), now, writable=False)
    assert not (reader["confirm"] or reader["check_in"] or reader["no_show"])
    assert (_waited(0), _waited(59), _waited(75)) == ("há menos de 1 min", "há 59 min", "há 1 h 15 min")


# ------------------------------------------------------------------------ the reception (#129)


def test_the_reception_board_says_who_with_whom_and_since_when(ready, afternoon, subtests):
    now = afternoon.now
    late = fit_in(ready, now - timedelta(minutes=30), "late")
    ahead = fit_in(ready, now + timedelta(hours=2), "ahead")
    waiting = fit_in(ready, now - timedelta(hours=1), "waiting")
    afternoon.now = now - timedelta(minutes=12)
    step(ready, "check_in", waiting)
    afternoon.now = now
    client = client_for(ready.a.reception)
    reception = url(ready, "reception")
    with subtests.test("time, patient, kind and professional, by schedule"):
        html = page(client, reception)
        assert 'http-equiv="refresh"' not in html
        board = content(html)
        assert '<h2 id="schedule-' in board and "Agenda da Dra. Ana" in board and board.count("Dra. Ana") >= 4
        assert board.count(">Consulta<") >= 3 and "Maria Paciente Secreta" in board
        assert ">14:30</time>" in board and ">17:00</time>" in board
    with subtests.test("the wait and the delay"):
        assert "Chegou às" in board and ">14:48</time> · há 12 min" in board
        assert board.count("Atrasado<") == 1  # The marker; "Atrasados" is the count.
    with subtests.test("the counts link to the filtered board"):
        counts = re.search(r'<dl class="stat-grid reception-counts">(.*?)</dl>', board, re.S).group(1)
        values = dict(re.findall(r'href="[^"]*\?show=([a-z_]+)#board"[^>]*>(\d+)<', counts))
        assert values == {"waiting": "1", "late": "1", "in_progress": "0"}
        late_only = content(page(client, reception, show="late"))
        assert url(ready, "appointment", late.sysid) in late_only
        assert url(ready, "appointment", ahead.sysid) not in late_only
        assert url(ready, "appointment", waiting.sysid) not in late_only
        assert 'aria-current="true">1<' in late_only
    with subtests.test("no reload by itself: a link to refresh, and an optional script"):
        assert f'href="{reception}" data-reception-refresh>Atualizar</a>' in board and ">15:00</time>" in board
        assert re.search(r'<script src="[^"]*med_scheduling\.js" defer></script>', html)
        assert 'aria-live="polite"' in html and "data-reception-board" in html
        assert "1 aguardando, 1 atrasados e 0 em atendimento, de 3 consultas hoje." in html
    with subtests.test("confirm, arrive and no-show from the board"):
        assert f'action="{url(ready, "transition", ahead.sysid, "confirm")}"' in board
        assert f'action="{url(ready, "check-in", late.sysid)}"' in board
        no_show = url(ready, "transition", late.sysid, "mark_no_show")
        assert f'href="{no_show}?next=reception"' in board
        # Not before the start: the appointment still ahead has no "Marcar falta".
        assert url(ready, "transition", ahead.sysid, "mark_no_show") not in board
        asked = page(client, no_show, next="reception")
        assert 'name="next" value="reception"' in asked
        response = client.post(
            no_show, {"revision": row_of(ready, late.sysid).appointment.revision, "next": "reception"}
        )
        assert (response.status_code, response["Location"]) == (302, reception)
        assert row_of(ready, late.sysid).appointment.status == "no_show"
        response = client.post(
            url(ready, "transition", ahead.sysid, "confirm"),
            {"revision": row_of(ready, ahead.sysid).appointment.revision, "next": "reception"},
        )
        assert (response.status_code, response["Location"]) == (302, reception)
        assert row_of(ready, ahead.sysid).appointment.status == "confirmed"


def test_an_arrival_is_undone_from_the_board_within_the_window(ready, afternoon, subtests):
    appointment = fit_in(ready, afternoon.now + timedelta(minutes=20), "soon")
    step(ready, "confirm", appointment)
    client = client_for(ready.a.reception)
    reception = url(ready, "reception")
    undo = url(ready, "undo-check-in", appointment.sysid)

    def revision():
        return row_of(ready, appointment.sysid).appointment.revision

    with subtests.test("offered right after the arrival, and back to confirmed"):
        client.post(url(ready, "check-in", appointment.sysid), {"revision": revision(), "next": "reception"})
        board = content(page(client, reception))
        assert f'action="{undo}"' in board and "Desfazer chegada" in board
        response = client.post(undo, {"revision": revision(), "next": "reception"}, follow=True)
        assert response.redirect_chain[-1][0] == reception
        assert "Chegada desfeita: a consulta voltou a ficar confirmada." in response.content.decode()
        detail = row_of(ready, appointment.sysid)
        assert (detail.appointment.status, detail.arrived_at) == ("confirmed", None)
    with subtests.test("not after the window"):
        client.post(url(ready, "check-in", appointment.sysid), {"revision": revision(), "next": "reception"})
        afternoon.now += timedelta(minutes=CHECK_IN_UNDO_MINUTES, seconds=1)
        assert f'action="{undo}"' not in content(page(client, reception))
        response = client.post(undo, {"revision": revision(), "next": "reception"}, follow=True)
        assert "para desfazer a chegada terminou" in response.content.decode()
        assert row_of(ready, appointment.sysid).appointment.status == "arrived"
    with subtests.test("a GET does nothing"):
        assert client.get(undo).status_code == 405
    with subtests.test("who cannot register the arrival does not undo it"):
        with ready.as_user(ready.a.admin) as admin:
            current = SchedulingService().schedule(actor=admin, schedule_id=ready.schedule.sysid)
            SchedulingService().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(ready.a.groups["reception"],),
                reader_group_ids=(ready.a.groups["finance"],),
                expected_revision=current.revision,
            )
        afternoon.now -= timedelta(minutes=CHECK_IN_UNDO_MINUTES)
        reader = client_for(ready.a.finance)
        assert "Desfazer chegada" not in content(page(reader, reception))
        assert reader.post(undo, {"revision": revision()}).status_code == 404
        outsider = client_for(ready.b.reception)
        assert (
            outsider.post(url(ready, "undo-check-in", appointment.sysid, organization=ready.org_b)).status_code == 404
        )
        assert row_of(ready, appointment.sysid).appointment.status == "arrived"


# ------------------------------------------------------------------------ booking (#130)


def test_the_search_tells_namesakes_apart_and_offers_to_register(ready):
    from .helpers import new_patient

    new_patient(ready, full_name="Maria Paciente Secreta", birth_date=date(1980, 5, 17))
    client = client_for(ready.a.reception)
    query = {"schedule": ready.schedule.sysid, "day": ready.monday.isoformat(), "slot": at(ready, 10).isoformat()}
    html = page(client, url(ready, "book"), q="Maria", **query)
    rows = re.findall(r"<tr><td data-label=\"Paciente\">.*?</tr>", html, re.S)
    assert len(rows) == 2 and any('datetime="1980-05-17"' in row for row in rows)
    # Birth date and code tell namesakes apart; the summary carries no contact, so no phone column (#130).
    assert all('data-label="Nascimento"' in row and 'data-label="Telefone"' not in row for row in rows)
    link = re.search(r'href="([^"]*/apps/med_patients/new/\?next=[^"]+)"', html).group(1).replace("&amp;", "&")
    (back,) = parse_qs(urlsplit(link).query)["next"]
    assert back.startswith(url(ready, "book") + "?")
    assert parse_qs(urlsplit(back).query) == {key: [str(value)] for key, value in query.items()}
    assert "Maria" not in link  # Nothing of the search, nor of the patient, goes in the address.
    # The patients app sends the person back with the patient created: the booking opens on it.
    back_page = page(client, back + f"&patient={ready.patient.sysid}")
    assert re.search(r'name="slot" value="[^"]+" checked', back_page)
    assert f'<option value="{ready.schedule.sysid}" selected>' in back_page


def test_the_slot_plan_moves_by_day_and_says_the_time_on_the_button(ready):
    client = client_for(ready.a.reception)
    query = {
        "patient": ready.patient.sysid,
        "schedule": ready.schedule.sysid,
        "appointment_type": ready.kind.sysid,
        "day": ready.monday.isoformat(),
    }
    html = page(client, url(ready, "book"), **query)
    for day in (ready.monday - timedelta(days=1), ready.monday + timedelta(days=1)):
        assert f"day={day.isoformat()}" in html
    assert re.search(r"data-slot-submit>Marcar consulta</button>", html)
    assert 'data-submit-label="Marcar consulta às 10:00"' in html
    picked = page(client, url(ready, "book"), **query, slot=at(ready, 10).isoformat())
    assert re.search(r"data-slot-submit>Marcar consulta às 10:00</button>", picked)
    # The time of a fit-in folds with the box (optional script); the server still checks it.
    assert "data-fit-in-toggle" in html and re.search(r"<div data-fit-in-only>.*?name=\"fit_in_time\"", html, re.S)


def test_the_waitlist_says_when_someone_leaves_it(ready):
    with ready.as_user(ready.a.reception) as actor:
        entry = SchedulingService().add_to_waitlist(
            actor=actor,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            preferred_period="any",
            earliest_date=ready.monday,
            idempotency_key="leave",
        )
    client = client_for(ready.a.reception)
    response = client.post(url(ready, "waitlist-cancel", entry.sysid), {"revision": entry.revision}, follow=True)
    assert "Paciente tirado da lista de espera." in response.content.decode()


# ------------------------------------------------------------------------ the appointment page (#131)


def attend_and_collect(*_args, **_kwargs):
    return (
        AppointmentActionInfo("med_records.attend", "Atender", "med_records:attend", 10),
        AppointmentActionInfo("med_finance.collect", "Receber", "med_finance:collect", 20),
    )


def test_the_appointment_page_has_one_main_action_and_the_rest_under_alterar(ready, monkeypatch, subtests):
    from .booking import book

    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    address = url(ready, "appointment", appointment.sysid)
    with subtests.test("who, with whom and what"):
        html = content(page(client, address))
        assert "Dra. Ana" in html and "Agenda da Dra. Ana" in html and ">Consulta<" in html
        patient = reverse("med_patients:detail", args=(ready.org_a.pk, ready.patient.sysid))
        assert f'<a href="{patient}">Maria Paciente Secreta</a>' in html
    with subtests.test("scheduled: confirming is the main action; the changes are folded"):
        assert html.count("btn-primary") == 1
        assert re.search(r'class="btn btn-primary">Confirmar<', html)
        assert re.search(
            r'<details class="card mb-6 appointment-change">\s*<summary><h2 id="change-heading">Alterar', html
        )
        assert html.index("<details") < html.index("Trocar a modalidade") < html.index("reschedule-heading")
    step(ready, "check_in", appointment)
    with subtests.test("arrived, without the records app: starting the care is the main action"):
        monkeypatch.setattr(SchedulingService, "appointment_actions", lambda *a, **k: ())
        html = content(page(client, address))
        assert html.count("btn-primary") == 1 and re.search(r'class="btn btn-primary">Iniciar atendimento<', html)
    with subtests.test("arrived, with Atender: no Iniciar atendimento, and the actions are sent by POST"):
        monkeypatch.setattr(SchedulingService, "appointment_actions", attend_and_collect)
        html = content(page(client, address))
        assert "Iniciar atendimento" not in html and html.count("btn-primary") == 1
        attend = reverse("med_records:attend", args=(ready.org_a.pk, appointment.sysid))
        collect = reverse("med_finance:collect", args=(ready.org_a.pk, appointment.sysid))
        assert re.search(
            rf'<form method="post" action="{attend}"><input type="hidden" name="csrfmiddlewaretoken"[^>]*><button type="submit" class="btn btn-primary">Atender</button></form>',
            html,
        )
        assert re.search(rf'<form method="post" action="{collect}">.*?class="btn btn-secondary">Receber<', html)
        assert f'href="{attend}"' not in html and f'href="{collect}"' not in html
    with subtests.test("the arrival can be undone for a few minutes"):
        assert f'action="{url(ready, "undo-check-in", appointment.sysid)}"' in html


def test_an_unknown_appointment_is_not_found(ready):
    assert client_for(ready.a.reception).get(url(ready, "appointment", uuid4())).status_code == 404
