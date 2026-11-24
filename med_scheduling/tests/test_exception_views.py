"""Pages of the exception of a day: its periods changed in two steps, and the grid that offers a later validity."""

import re
from datetime import date, timedelta

import pytest
from django.utils import timezone

from applications.med_patients.service_api import PatientService

from ..service_api import AvailabilityRuleInput, SchedulingService
from .booking import SP, book, prepare
from .helpers import new_patient
from .test_views import assert_safe, client_for, let_finance_read, schedule_revision, url

START = date(2026, 1, 1)
MORNING = AvailabilityRuleInput(0, 8 * 60, 12 * 60, START)
TUESDAY_QUEUE = AvailabilityRuleInput(1, 8 * 60, 12 * 60, START, mode="walk_in")


def service():
    return SchedulingService()


@pytest.fixture
def ready(clinic):
    """Mondays: booked time from 08:00 to 12:00. Tuesdays: walk-in from 08:00 to 12:00."""
    ready = prepare(clinic)
    with ready.as_user(ready.a.reception) as actor:
        current = service().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
        service().set_availability(
            actor=actor, schedule_id=ready.schedule.sysid, rules=(MORNING, TUESDAY_QUEUE), expected_revision=current
        )
    ready.tuesday = ready.monday + timedelta(days=1)
    return ready


def page(ready, day=None, organization=None, **query):
    address = url(ready, "day-exception", ready.schedule.sysid, organization=organization)
    extra = "".join(f"&{name}={value}" for name, value in query.items())
    return f"{address}?date={day or ready.monday:%Y-%m-%d}{extra}"


def send(client, ready, day=None, revision=None, form="change", **fields):
    values = {"form": form, "revision": revision or schedule_revision(ready), **fields}
    return client.post(page(ready, day), values)


def plan(ready, day=None):
    day = day or ready.monday
    with ready.as_user(ready.a.reception) as actor:
        found = service().day_plan(actor=actor, schedule_id=ready.schedule.sysid, start_date=day, end_date=day)
    return [(item.start_minute, item.end_minute, item.mode, item.capacity, item.is_exception) for item in found]


def detail(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return service().appointment(actor=actor, appointment_id=appointment.sysid).appointment


def step(ready, name, appointment, **extra):
    current = detail(ready, appointment)
    with ready.as_user(ready.a.reception) as actor:
        return getattr(service(), name)(
            actor=actor, appointment_id=current.sysid, expected_revision=current.revision, **extra
        )


def affected(html):
    return re.findall(r'<input type="hidden" name="affected" value="([0-9a-f-]{36})">', html)


def test_the_periods_of_a_day_are_changed_on_its_page(ready, subtests):
    client = client_for(ready.a.reception)
    day_page = url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"
    with subtests.test("the page comes filled with the periods the day follows"):
        html = assert_safe(client.get(page(ready)))
        assert re.search(rf"<h1>Alterar <time[^>]*>[^<]*{ready.monday:%d/%m/%Y}</time></h1>", html)
        assert "Este dia segue a grade semanal." in html and "Voltar à grade semanal" not in html
        assert re.search(r'name="start_1"[^>]*value="08:00"', html) and re.search(
            r'name="end_1"[^>]*value="12:00"', html
        )
        assert len(re.findall(r"<fieldset[^>]*data-period data-period-line", html)) == 4
        assert len(re.findall(r"<fieldset[^>]*data-period-line data-empty", html)) == 3
        assert re.search(r'<script src="[^"]*med_scheduling/med_scheduling\.js" defer></script>', html)
        assert "Trocar para ordem de chegada" in html and "mode=walk_in" in html
    with subtests.test("the day and the week lead to it"):
        html = assert_safe(client.get(day_page))
        assert "Alterar este dia" in html and page(ready).replace("&", "&amp;") in html
        week = assert_safe(client.get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday.isoformat()}))
        assert week.count("Alterar este dia") == 7 and "Dia alterado" not in week
        schedule = assert_safe(client.get(url(ready, "schedule", ready.schedule.sysid)))
        assert "Nenhum dia alterado daqui para a frente." in schedule
        assert f'action="{url(ready, "day-exception", ready.schedule.sysid)}"' in schedule
    with subtests.test("what the form refuses is told on the field"):
        cases = {
            "id_start_2": {"start_1": "08:00", "end_1": "12:00", "start_2": "11:00", "end_2": "13:00"},
            "id_start_1": {},
            "id_capacity_1": {"start_1": "08:00", "end_1": "12:00", "capacity_1": "5"},
            "id_end_1": {"start_1": "12:00", "end_1": "08:00"},
            "id_start_3": {"start_1": "08:00", "end_1": "12:00", "capacity_3": "5", "mode_3": "walk_in"},
        }
        for field, values in cases.items():
            response = send(client, ready, **values)
            assert response.status_code == 400 and f'href="#{field}"' in response.content.decode(), field
        html = send(client, ready, **cases["id_start_2"]).content.decode()
        assert "11:00–13:00 se sobrepõe ao período 08:00–12:00" in html
        assert "Informe ao menos um período" in send(client, ready).content.decode()
        assert plan(ready) == [(480, 720, "booked", None, False)]
    with subtests.test("saved, the day follows its own periods"):
        response = send(
            client,
            ready,
            start_1="14:00",
            end_1="16:00",
            start_2="16:00",
            end_2="18:00",
            mode_2="walk_in",
            capacity_2="6",
        )
        assert response.status_code == 302 and response["Location"] == day_page
        assert "Períodos do dia salvos." in client.get(day_page).content.decode()
        assert plan(ready) == [(840, 960, "booked", None, True), (960, 1080, "walk_in", 6, True)]
        html = assert_safe(client.get(page(ready)))
        assert "Este dia já foi alterado" in html and "Voltar à grade semanal" in html
        assert re.search(r'name="capacity_2"[^>]*value="6"', html)
        assert re.search(r'<select name="mode_2".*?<option value="walk_in" selected>', html, re.S)
        week = assert_safe(client.get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday.isoformat()}))
        assert week.count("Dia alterado") == 1
        schedule = assert_safe(client.get(url(ready, "schedule", ready.schedule.sysid)))
        assert (
            f"{ready.monday:%d/%m/%Y}" in schedule
            and "14:00–16:00 Hora marcada; 16:00–18:00 Ordem de chegada" in schedule
        )
    with subtests.test("a page that opened before another change saves nothing"):
        response = send(client, ready, revision=1, start_1="09:00", end_1="10:00")
        assert response.status_code == 302 and response["Location"] == page(ready)
        assert "A agenda mudou desde que a página abriu" in client.get(page(ready)).content.decode()
        assert len(plan(ready)) == 2
    with subtests.test("back to the weekly grid"):
        response = send(client, ready, form="clear")
        assert response.status_code == 302 and response["Location"] == day_page
        assert "O dia voltou a seguir a grade semanal." in client.get(day_page).content.decode()
        assert plan(ready) == [(480, 720, "booked", None, False)]


def test_a_day_becomes_walk_in_in_two_steps(ready, subtests):
    client = client_for(ready.a.reception)
    first = book(ready, 9, key="first")
    second = step(ready, "confirm", book(ready, 10, key="second", patient_id=new_patient(ready).sysid))
    morning = {"start_1": "08:00", "end_1": "12:00", "mode_1": "walk_in", "capacity_1": "15"}
    with subtests.test("the shortcut fills the form, and changes nothing"):
        html = assert_safe(client.get(page(ready, mode="walk_in")))
        assert "Os períodos abaixo já estão como ordem de chegada." in html
        assert re.search(r'<select name="mode_1".*?<option value="walk_in" selected>', html, re.S)
        assert "Trocar para ordem de chegada" not in html and plan(ready) == [(480, 720, "booked", None, False)]
    with subtests.test("the first step lists what moves and changes nothing"):
        response = send(client, ready, **morning)
        html = assert_safe(response)
        assert "Confira as consultas que mudam" in html and "Nada foi alterado ainda." in html
        assert first.code in html and second.code in html and "Maria Paciente Secreta" in html
        assert html.count("Passa para a ordem de chegada das 08:00–12:00.") == 2
        assert sorted(affected(html)) == sorted([str(first.sysid), str(second.sysid)])
        assert '<input type="hidden" name="step" value="confirm">' in html
        assert '<input type="hidden" name="mode_1" value="walk_in">' in html
        assert '<input type="hidden" name="capacity_1" value="15">' in html
        assert "Confirmar e mover 2 consultas" in html
        assert plan(ready) == [(480, 720, "booked", None, False)] and detail(ready, first).mode == "booked"
    seen = affected(html)
    with subtests.test("a booking made meanwhile asks for another look"):
        late = book(ready, 11, key="late", patient_id=new_patient(ready).sysid)
        response = send(client, ready, step="confirm", affected=seen, **morning)
        html = assert_safe(response)
        assert "As consultas deste dia mudaram desde a conferência." in html and late.code in html
        assert len(affected(html)) == 3 and detail(ready, first).mode == "booked"
    with subtests.test("who does not read the patient sees the code only"):
        with ready.as_user(ready.a.admin) as admin:
            service().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(ready.a.groups["reception"], ready.a.groups["finance"]),
                reader_group_ids=(),
                writer_user_ids=(),
                expected_revision=service().schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
            )
            registry = PatientService().registries(actor=admin)[0]
        from skeleton.service_api.access import AccessService

        with ready.as_user(ready.a.admin) as admin:
            AccessService().revoke_record_access(
                actor=admin,
                table_key="med_patients.patientregistry",
                record_id=registry.sysid,
                group_id=ready.a.groups["finance"],
                action="read",
            )
        html = assert_safe(send(client_for(ready.a.finance), ready, **morning))
        assert first.code in html and "Paciente não disponível" in html and "Maria Paciente Secreta" not in html
    with subtests.test("confirmed with the list of now, the appointments go to the session"):
        response = send(client, ready, step="confirm", affected=affected(html), **morning)
        assert response.status_code == 302
        after = client.get(response["Location"]).content.decode()
        assert (
            "Períodos do dia salvos." in after and "3 consultas passaram para a ordem de chegada do período." in after
        )
        assert plan(ready) == [(480, 720, "walk_in", 15, True)]
        assert [detail(ready, row).mode for row in (first, second, late)] == ["walk_in"] * 3
        assert detail(ready, second).status == "scheduled" and detail(ready, second).code == second.code
    with subtests.test("what no confirmation overcomes is told, with no way to confirm"):
        response = send(client, ready, start_1="14:00", end_1="18:00")
        html = response.content.decode()
        assert response.status_code == 400 and "Consultas que impedem a mudança" in html
        assert html.count("Fica fora dos períodos do dia.") == 3 and 'name="step"' not in html
        assert re.search(r'name="start_1"[^>]*value="14:00"', html), "the periods typed stay on the form"
        response = send(client, ready, form="clear")
        html = response.content.decode()
        assert response.status_code == 400 and "o período passaria a ter hora marcada" in html
        assert plan(ready) == [(480, 720, "walk_in", 15, True)]
    with subtests.test("a forged list of appointments is not a confirmation"):
        assert send(client, ready, step="confirm", affected=["not-an-id"], **morning).status_code == 404


def test_who_does_not_write_the_schedule_does_not_change_its_days(ready, subtests):
    client = client_for(ready.a.reception)
    fields = {"start_1": "14:00", "end_1": "16:00"}
    with subtests.test("who only reads the schedule"):
        reader = let_finance_read(ready)
        assert reader.get(page(ready)).status_code == send(reader, ready, **fields).status_code == 404
        assert send(reader, ready, form="clear").status_code == 404
        day = assert_safe(reader.get(url(ready, "day"), {"date": ready.monday.isoformat()}))
        assert "Agenda da Dra. Ana" in day and "Alterar este dia" not in day
        week = assert_safe(reader.get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday.isoformat()}))
        assert "Alterar este dia" not in week
        schedule = assert_safe(reader.get(url(ready, "schedule", ready.schedule.sysid)))
        assert "Dias alterados" in schedule and "day-exception" not in schedule and 'name="date"' not in schedule
    with subtests.test("another organization"):
        outsider = client_for(ready.b.reception)
        foreign = page(ready, organization=ready.org_b)
        assert outsider.get(foreign).status_code == 404
        assert outsider.post(foreign, {"form": "change", "revision": 1, **fields}).status_code == 404
    with subtests.test("a day that is over is shown and not changed"):
        yesterday = timezone.localdate(timezone=SP) - timedelta(days=1)
        html = assert_safe(client.get(page(ready, yesterday)))
        assert "Este dia já passou" in html and 'name="start_1"' not in html
        assert send(client, ready, yesterday, **fields).status_code == 404
        past_week = assert_safe(
            client.get(
                url(ready, "week", ready.schedule.sysid), {"start": (yesterday - timedelta(days=14)).isoformat()}
            )
        )
        assert "Alterar este dia" not in past_week
    with subtests.test("what is not a day, and what is not a form of the page"):
        address = url(ready, "day-exception", ready.schedule.sysid)
        assert client.get(address + "?date=amanha").status_code == 404
        assert send(client, ready, form="other", **fields).status_code == 404
    assert plan(ready) == [(480, 720, "booked", None, False)]


def test_the_grid_offers_a_later_validity_when_a_mode_changes_under_appointments(ready, subtests):
    client = client_for(ready.a.reception)
    timed = book(ready, 9, key="timed")
    with ready.as_user(ready.a.reception) as actor:
        monday_rule, _tuesday = service().availability(actor=actor, schedule_id=ready.schedule.sysid)
    edit = url(ready, "period-edit", ready.schedule.sysid, monday_rule.sysid)
    values = {"weekday": "0", "start": "08:00", "end": "12:00", "valid_from": "2026-01-01", "mode": "walk_in"}
    following = ready.monday + timedelta(days=1)
    with subtests.test("refused, with the day from which the change holds"):
        response = client.post(edit, {**values, "revision": schedule_revision(ready)})
        html = response.content.decode()
        assert response.status_code == 400
        assert f"têm consultas marcadas até {ready.monday:%d/%m/%Y}" in html
        assert f'name="split_from" value="{following.isoformat()}"' in html
        assert re.search(rf"Mudar a partir de <time[^>]*>{following:%d/%m/%Y}</time>", html)
    with subtests.test("accepted from that day: the period stays as it is until the eve"):
        response = client.post(
            edit, {**values, "revision": schedule_revision(ready), "split_from": following.isoformat()}
        )
        assert response.status_code == 302
        with ready.as_user(ready.a.reception) as actor:
            rules = service().availability(actor=actor, schedule_id=ready.schedule.sysid)
        assert sorted((rule.weekday, rule.mode, rule.valid_from, rule.valid_until) for rule in rules) == [
            (0, "booked", START, ready.monday),
            (0, "walk_in", following, None),
            (1, "walk_in", START, None),
        ]
        assert detail(ready, timed).mode == "booked"
        assert plan(ready) == [(480, 720, "booked", None, False)]
        assert plan(ready, ready.monday + timedelta(days=7)) == [(480, 720, "walk_in", None, False)]
    with subtests.test("a day that is not a day changes the period as typed"):
        ended = next(rule for rule in rules if rule.valid_until == ready.monday)
        edit = url(ready, "period-edit", ready.schedule.sysid, ended.sysid)
        response = client.post(
            edit, {**values, "mode": "booked", "revision": schedule_revision(ready), "split_from": "amanha"}
        )
        assert response.status_code == 400 and "se sobrepõe" in response.content.decode()
