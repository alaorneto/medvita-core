"""Pages of the walk-in mode: the grid with mode and capacity, booking a period, the session card and the queue."""

import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import resolve
from django.utils import timezone

from ..service_api import AvailabilityRuleInput, ScheduleTypeInput, SchedulingService
from .booking import SP, at, book, prepare
from .helpers import new_patient
from .test_views import add_kind, assert_safe, client_for, let_finance_read, schedule_revision, take, url

START = date(2026, 1, 1)
AFTERNOON = AvailabilityRuleInput(0, 14 * 60, 18 * 60, START)


def service():
    return SchedulingService()


def walk_in(start=8, end=12, *, capacity=15, kinds=(), weekday=0):
    return AvailabilityRuleInput(
        weekday, start * 60, end * 60, START, appointment_type_ids=kinds, mode="walk_in", capacity=capacity
    )


def set_grid(ready, *rules):
    revision = schedule_revision(ready)
    with ready.as_user(ready.a.reception) as actor:
        return service().set_availability(
            actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=revision
        )


def grid(ready):
    with ready.as_user(ready.a.reception) as actor:
        return service().availability(actor=actor, schedule_id=ready.schedule.sysid)


@pytest.fixture
def ready(clinic):
    """Mondays: walk-in from 08:00 to 12:00 with 15 places, booked time from 14:00 to 18:00."""
    ready = prepare(clinic)
    set_grid(ready, walk_in(), AFTERNOON)
    return ready


def arrive(ready, key, hour=9, **extra):
    return book(ready, hour, key=key, mode="walk_in", **extra)


def detail(ready, appointment):
    with ready.as_user(ready.a.reception) as actor:
        return service().appointment(actor=actor, appointment_id=appointment.sysid)


def sessions(ready, day=None):
    with ready.as_user(ready.a.reception) as actor:
        return service().queue(actor=actor, schedule_id=ready.schedule.sysid, date=day or ready.monday)


def booked(ready, patient=None):
    with ready.as_user(ready.a.reception) as actor:
        return list(service().appointments(actor=actor, patient_id=(patient or ready.patient).sysid).items)


def session_value(ready, hour=8, day=None):
    """The value of the choice of a walk-in period on the booking page."""
    return "walk_in:" + at(ready, hour, day=day).astimezone(UTC).isoformat()


def choices(html):
    return re.findall(r'name="slot" value="([^"]+)"', html)


def booking_query(ready, **values):
    return {
        "patient": ready.patient.sysid,
        "schedule": ready.schedule.sysid,
        "appointment_type": ready.kind.sysid,
        "day": ready.monday.isoformat(),
        **values,
    }


# ----------------------------------------------------------------------------- the weekly grid


def test_the_grid_editor_takes_the_mode_and_the_capacity_of_a_period(ready, subtests):
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)

    def add(**fields):
        fields = {f"periods-{name}": value for name, value in {"valid_from": "2026-01-01", **fields}.items()}
        return client.post(page, {"form": "periods", "revision": schedule_revision(ready), **fields})

    def modes():
        return {(rule.weekday, rule.start_minute): (rule.mode, rule.capacity) for rule in grid(ready)}

    with subtests.test("the cards of the week say the mode and the places"):
        html = assert_safe(client.get(page))
        assert re.search(r"<p>Ordem de chegada · 15 vagas</p>", html) and "<p>Hora marcada</p>" in html
        assert "data-period-mode" in html and "data-walk-in-only" in html
    with subtests.test("a walk-in period with places, on two weekdays at once"):
        response = add(weekdays=["2", "3"], start_1="08:00", end_1="12:00", mode="walk_in", capacity="1")
        assert response.status_code == 302
        assert modes()[(2, 480)] == modes()[(3, 480)] == ("walk_in", 1)
        assert "Ordem de chegada · 1 vaga<" in assert_safe(client.get(page))
    with subtests.test("without places the period takes what fits its time"):
        assert add(weekdays=["4"], start_1="08:00", end_1="12:00", mode="walk_in").status_code == 302
        assert modes()[(4, 480)] == ("walk_in", None)
        assert "Ordem de chegada · sem limite de vagas" in assert_safe(client.get(page))
    saved = modes()
    with subtests.test("places are of a walk-in period: the mistake goes to the field"):
        response = add(weekdays=["5"], start_1="08:00", end_1="12:00", mode="booked", capacity="10")
        html = response.content.decode()
        assert response.status_code == 400 and "Vagas valem só na ordem de chegada" in html
        assert 'href="#id_periods-capacity"' in html
        assert add(weekdays=["5"], start_1="08:00", end_1="12:00", mode="walk_in", capacity="0").status_code == 400
        assert add(weekdays=["5"], start_1="08:00", end_1="12:00", mode="queue").status_code == 400
    with subtests.test("a kind the schedule does not take by order of arrival"):
        take(ready, ScheduleTypeInput(ready.kind.sysid, allow_walk_in=False))
        response = add(weekdays=["5"], start_1="08:00", end_1="12:00", mode="walk_in", kinds=[str(ready.kind.sysid)])
        html = response.content.decode()
        assert response.status_code == 400 and "A agenda não atende por ordem de chegada: Consulta." in html
        assert 'href="#id_periods-kinds_0"' in html
        assert "só com hora marcada" in assert_safe(client.get(page))
        take(ready)
    assert modes() == saved
    with subtests.test("a period changes its mode on its own page and keeps its row"):
        afternoon = next(rule for rule in grid(ready) if rule.start_minute == 840)
        address = url(ready, "period-edit", ready.schedule.sysid, afternoon.sysid)
        html = assert_safe(client.get(address))
        assert re.search(r'<option value="booked" selected>', html) and "data-walk-in-only" in html
        fields = {"weekday": "0", "start": "14:00", "end": "18:00", "valid_from": "2026-01-01"}
        response = client.post(
            address, {**fields, "mode": "walk_in", "capacity": "20", "revision": schedule_revision(ready)}
        )
        assert response.status_code == 302
        changed = next(rule for rule in grid(ready) if rule.start_minute == 840)
        assert (changed.sysid, changed.mode, changed.capacity) == (afternoon.sysid, "walk_in", 20)
        html = assert_safe(client.get(address))
        assert re.search(r'<option value="walk_in" selected>', html)
        assert re.search(r'name="capacity"[^>]*value="20"', html)
        response = client.post(
            address, {**fields, "mode": "booked", "capacity": "20", "revision": schedule_revision(ready)}
        )
        assert response.status_code == 400 and "Vagas valem só na ordem de chegada" in response.content.decode()
        response = client.post(address, {**fields, "mode": "booked", "revision": schedule_revision(ready)})
        assert response.status_code == 302
        assert modes()[(0, 840)] == ("booked", None)


def test_the_kinds_of_a_schedule_say_how_they_are_taken(ready, subtests):
    insured = add_kind(ready)
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)

    def name(prefix, kind):
        return f"types-{prefix}_{kind.sysid.hex}"

    def save(**fields):
        return client.post(
            page, {"form": "types", "revision": schedule_revision(ready), "types-scope": "chosen", **fields}
        )

    def taken():
        with ready.as_user(ready.a.reception) as actor:
            found = service().schedule_types(actor=actor, schedule_id=ready.schedule.sysid)
        return {item.appointment_type_id: (item.allow_booked, item.allow_walk_in) for item in found}

    with subtests.test("every kind starts ticked for the two modes"):
        html = assert_safe(client.get(page))
        for prefix in ("booked", "walk_in"):
            assert re.search(rf'name="{name(prefix, insured)}"[^>]*checked', html)
    with subtests.test("a kind of booked time only, another of the two modes"):
        response = save(
            **{
                name("on", insured): "on",
                name("booked", insured): "on",
                name("on", ready.kind): "on",
                name("booked", ready.kind): "on",
                name("walk_in", ready.kind): "on",
            }
        )
        assert response.status_code == 302
        assert taken() == {insured.sysid: (True, False), ready.kind.sysid: (True, True)}
        html = assert_safe(client.get(page))
        walk_in_box = name("walk_in", insured)
        assert "só com hora marcada" in html and not re.search(rf'name="{walk_in_box}"[^>]*checked', html)
    with subtests.test("a ticked kind says at least one mode"):
        response = save(**{name("on", insured): "on"})
        assert response.status_code == 400 and "Marque como a agenda atende Unimed" in response.content.decode()
        assert taken()[insured.sysid] == (True, False)


# ----------------------------------------------------------------------------------- booking


def test_booking_shows_the_periods_of_the_day_and_books_a_walk_in(ready, subtests):
    client = client_for(ready.a.reception)
    address = url(ready, "book")
    morning = session_value(ready)

    with subtests.test("the periods of the day, each with its mode and what is taken"):
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "08:00–12:00 · Ordem de chegada" in html and "0 de 15 vagas" in html
        assert "14:00–18:00 · Hora marcada" in html and "0 consultas marcadas" in html
        found = choices(html)
        assert found[0] == morning and len(found) == 1 + 8
        assert {datetime.fromisoformat(value) for value in found[1:]} >= {at(ready, 14), at(ready, 17, 30)}
    with subtests.test("nothing chosen"):
        response = client.post(address, booking_query(ready, idempotency_key="nothing"))
        assert response.status_code == 400 and "Escolha um horário, ou um período de ordem de chegada" in (
            response.content.decode()
        )
    with subtests.test("the period is booked without a time"):
        response = client.post(address, booking_query(ready, slot=morning, idempotency_key="first"))
        assert response.status_code == 302
        (row,) = booked(ready)
        assert (row.mode, row.starts_at, row.ends_at) == ("walk_in", at(ready, 8), at(ready, 12))
        assert response["Location"] == url(ready, "appointment", row.sysid)
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "1 de 15 vagas" in html
    with subtests.test("a time inside a walk-in period is of the other mode"):
        response = client.post(address, booking_query(ready, slot=at(ready, 9).isoformat(), idempotency_key="mismatch"))
        assert response.status_code == 400 and "atende de outro modo" in response.content.decode()
        assert len(booked(ready)) == 1
    with subtests.test("a full period says so, refuses and takes a fit-in"):
        set_grid(ready, walk_in(capacity=1), AFTERNOON)
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "1 de 1 vaga" in html and "Lotado" in html and "marque “Encaixe”" in html
        assert morning in choices(html)
        response = client.post(address, booking_query(ready, slot=morning, idempotency_key="full"))
        html = response.content.decode()
        assert response.status_code == 400 and "está lotado" in html and "marque “Encaixe”" in html
        assert re.search(rf'name="slot" value="{re.escape(morning)}" checked', html)
        response = client.post(address, booking_query(ready, slot=morning, fit_in="on", idempotency_key="fit"))
        assert response.status_code == 302
        fitted = max(booked(ready), key=lambda row: row.code)
        assert (fitted.mode, fitted.is_fit_in, fitted.starts_at) == ("walk_in", True, at(ready, 8))
    with subtests.test("a fit-in with a time is taken inside the walk-in period"):
        response = client.post(address, booking_query(ready, fit_in="on", fit_in_time="09:30", idempotency_key="timed"))
        assert response.status_code == 302
        timed = max(booked(ready), key=lambda row: row.code)
        assert (timed.mode, timed.is_fit_in, timed.starts_at) == ("booked", True, at(ready, 9, 30))
    with subtests.test("a kind the schedule does not take by order of arrival"):
        take(ready, ScheduleTypeInput(ready.kind.sysid, allow_walk_in=False))
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "A agenda não atende Consulta por ordem de chegada." in html and morning not in choices(html)
        response = client.post(address, booking_query(ready, slot=morning, idempotency_key="kind"))
        assert response.status_code == 400 and "não atende este tipo de atendimento" in response.content.decode()
        take(ready, ScheduleTypeInput(ready.kind.sysid, allow_booked=False))
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "A agenda não atende Consulta com hora marcada." in html and choices(html) == [morning]
        take(ready)
    with subtests.test("a period that lists other kinds takes this one only as a fit-in"):
        insured = add_kind(ready)
        set_grid(ready, walk_in(kinds=(insured.sysid,)), AFTERNOON)
        html = assert_safe(client.get(address, booking_query(ready)))
        assert "Este período não atende Consulta: só como encaixe." in html
    with subtests.test("a day the schedule does not work"):
        tuesday = ready.monday + timedelta(days=1)
        html = assert_safe(client.get(address, booking_query(ready, day=tuesday.isoformat())))
        assert "Esta agenda não atende neste dia." in html and choices(html) == []
        assert url(ready, "week", ready.schedule.sysid) + f"?start={tuesday:%Y-%m-%d}" in html


def test_a_walk_in_from_the_waitlist_and_the_patient_tab(ready):
    with ready.as_user(ready.a.reception) as actor:
        entry = service().add_to_waitlist(
            actor=actor,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            earliest_date=ready.monday,
            idempotency_key="entry",
        )
    client = client_for(ready.a.reception)
    query = booking_query(ready, entry=entry.sysid, revision=entry.revision)
    response = client.post(url(ready, "book"), {**query, "slot": session_value(ready), "idempotency_key": "listed"})
    assert response.status_code == 302
    (row,) = booked(ready)
    assert (row.mode, row.starts_at) == ("walk_in", at(ready, 8))
    html = assert_safe(client.get(url(ready, "patient_section", ready.patient.sysid)))
    assert "Ordem de chegada 08:00–12:00" in html


# ------------------------------------------------------------------------- day, week and queue


def test_day_and_week_show_the_session_with_its_occupancy(ready, subtests):
    first = arrive(ready, "a")
    other = new_patient(ready, full_name="Joaquim Outro Paciente")
    arrive(ready, "b", patient_id=other.sysid)
    with ready.as_user(ready.a.reception) as actor:
        service().check_in(actor=actor, appointment_id=first.sysid, expected_revision=first.revision)
    client = client_for(ready.a.reception)
    queue_page = url(ready, "queue", ready.schedule.sysid, ready.monday.isoformat())
    pages = {
        "day": url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}",
        "week": url(ready, "week", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}",
    }
    for name, address in pages.items():
        with subtests.test(page=name):
            html = assert_safe(client.get(address))
            assert "Ordem de chegada · 08:00–12:00" in html and "2 de 15 vagas" in html
            assert f'href="{queue_page}"' in html
            assert "nº&nbsp;1" in html and "Maria Paciente Secreta" in html and "Joaquim Outro Paciente" in html
            # A walk-in appointment has no time of its own: none is listed at 08:00.
            assert not re.search(r"<time[^>]*>08:00</time> · (Maria|Joaquim)", html)
            assert html.index("Fila") < html.index("Esperados")
    with subtests.test("an empty session still shows its places"):
        html = assert_safe(client.get(url(ready, "day") + f"?date={ready.monday + timedelta(days=7):%Y-%m-%d}"))
        assert "0 de 15 vagas" in html and "Nenhum paciente marcado." in html
    with subtests.test("who reads the schedule and not the patient"):
        reader = let_finance_read(ready)
        from applications.med_patients.service_api import PatientService
        from skeleton.service_api.access import AccessService

        with ready.as_user(ready.a.admin) as admin:
            registry = PatientService().registries(actor=admin)[0]
            AccessService().revoke_record_access(
                actor=admin,
                table_key="med_patients.patientregistry",
                record_id=registry.sysid,
                group_id=ready.a.groups["finance"],
                action="read",
            )
        for address in (*pages.values(), queue_page):
            html = assert_safe(reader.get(address))
            assert "Paciente não disponível" in html and "Maria Paciente Secreta" not in html
            assert "Registrar chegada" not in html and "Chegou agora" not in html


def test_the_day_page_query_count_does_not_grow_with_the_queue(ready):
    client = client_for(ready.a.reception)
    address = url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"

    def count():
        sizes = []
        for _ in range(2):
            with CaptureQueriesContext(connection) as context:
                assert client.get(address).status_code == 200
            sizes.append(len(context))
        return min(sizes)

    def another(key, *, arrived):
        patient = new_patient(ready, full_name=f"Paciente {key}")
        row = arrive(ready, key, patient_id=patient.sysid)
        if arrived:
            with ready.as_user(ready.a.reception) as actor:
                service().check_in(actor=actor, appointment_id=row.sysid, expected_revision=row.revision)

    another("one", arrived=True)
    client.get(address)
    one = count()
    for number in range(6):
        another(f"more-{number}", arrived=number % 2 == 0)
    assert count() == one


def test_the_queue_page_and_its_routes(ready, subtests):
    appointment = arrive(ready, "a")
    client = client_for(ready.a.reception)
    page = url(ready, "queue", ready.schedule.sysid, ready.monday.isoformat())
    with subtests.test("the queue of the day of a schedule"):
        html = assert_safe(client.get(page))
        assert "Agenda da Dra. Ana" in html and "Ordem de chegada · 08:00–12:00" in html
        assert "Ninguém aguardando." in html and "Maria Paciente Secreta" in html
        assert url(ready, "check-in", appointment.sysid) in html
    with subtests.test("a day without a walk-in period"):
        tuesday = (ready.monday + timedelta(days=1)).isoformat()
        html = assert_safe(client.get(url(ready, "queue", ready.schedule.sysid, tuesday)))
        assert "Esta agenda não atende por ordem de chegada neste dia." in html
    with subtests.test("who does not read the schedule, another organization and a date that is not one"):
        assert client_for(ready.a.finance).get(page).status_code == 404
        outsider = client_for(ready.b.reception)
        elsewhere = url(ready, "queue", ready.schedule.sysid, ready.monday.isoformat(), organization=ready.org_b)
        assert outsider.get(elsewhere).status_code == 404
        assert client.get(url(ready, "queue", ready.schedule.sysid, "tomorrow")).status_code == 404
    with subtests.test("the arrival and the priority come before the other transitions"):
        assert resolve(url(ready, "transition", appointment.sysid, "check_in")).url_name == "check-in"
        assert resolve(url(ready, "transition", appointment.sysid, "priority")).url_name == "priority"
        assert resolve(url(ready, "transition", appointment.sysid, "start")).url_name == "transition"
        assert client.post(url(ready, "transition", appointment.sysid, "delete"), {"revision": 1}).status_code == 404
        assert client.get(url(ready, "check-in", appointment.sysid)).status_code == 405
        assert client.get(url(ready, "priority", appointment.sysid)).status_code == 405


def test_the_reception_runs_the_queue_of_today(ready, subtests):
    today = timezone.localdate(timezone=SP)  # the day of the practice, the one the pages call today
    # The whole of today by order of arrival, so the session is open whenever the test runs.
    set_grid(ready, walk_in(0, 24, capacity=10, weekday=today.weekday()))
    patients = {
        name: new_patient(ready, full_name=name) for name in ("Ana Primeira", "Bento Segundo", "Clara Terceira")
    }
    rows = {}
    with ready.as_user(ready.a.reception) as actor:
        for name, patient in patients.items():
            rows[name] = service().book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=patient.sysid,
                appointment_type_id=ready.kind.sysid,
                starts_at=timezone.now(),
                mode="walk_in",
                idempotency_key=name,
            )
    client = client_for(ready.a.reception)
    reception = url(ready, "reception")
    queue_page = url(ready, "queue", ready.schedule.sysid, today.isoformat())

    def check_in(name, who=client, revision=None, **fields):
        fields = {"revision": revision or rows[name].revision, "next": "reception", **fields}
        return who.post(url(ready, "check-in", rows[name].sysid), fields)

    def waiting():
        (session,) = sessions(ready, today)
        return [(entry.appointment.arrival_number, entry.is_priority) for entry in session.waiting]

    with subtests.test("everybody is expected, each with the arrival"):
        html = assert_safe(client.get(reception))
        assert "Agenda da Dra. Ana" in html and "3 de 10 vagas" in html and "Ninguém aguardando." in html
        # The buttons of the queue (the header's "Registrar chegada" is a link to the board).
        assert html.count("Registrar chegada<span") == 3 and html.count("Chegada prioritária (Lei&nbsp;10.048)") == 3
        assert all(name in html for name in patients)
    with subtests.test("a page that opened before another change gives no number"):
        response = check_in("Ana Primeira", revision=99)
        assert response.status_code == 302 and waiting() == []
        assert "mudou desde que a página abriu" in client.get(reception).content.decode()
    with subtests.test("the arrival numbers and goes back to the reception"):
        response = check_in("Ana Primeira")
        assert (response.status_code, response["Location"]) == (302, reception)
        assert "Chegada registrada: chegada nº 1." in client.get(reception).content.decode()
        assert waiting() == [(1, False)]
    with subtests.test("the arrival with priority goes ahead in the queue"):
        response = check_in("Bento Segundo", priority="on", next="queue", schedule=ready.schedule.sysid, day=today)
        assert (response.status_code, response["Location"]) == (302, queue_page)
        assert waiting() == [(2, True), (1, False)]
        for address in (reception, queue_page):
            html = assert_safe(client.get(address))
            table = re.search(r"<tbody>(.*?)</tbody>", html[html.index("Chegada nº") :], re.S).group(1)
            assert table.index("Bento Segundo") < table.index("Ana Primeira")
            assert table.count("Prioritário") == 1 and "Clara Terceira" not in table
            assert html.count("Registrar chegada<span") == 1
    with subtests.test("who only reads the schedule sees the queue and registers nothing"):
        reader = let_finance_read(ready)
        html = assert_safe(reader.get(queue_page))
        assert "Bento Segundo" in html and "Registrar chegada" not in html and "Chegou agora" not in html
        assert check_in("Clara Terceira", who=reader).status_code == 404
        assert waiting() == [(2, True), (1, False)]
    with subtests.test("who arrives without a booking is booked and numbered in one step"):
        html = assert_safe(client.get(reception))
        link = re.search(r'href="([^"]+)">Chegou agora', html).group(1).replace("&amp;", "&")
        asked = {name: values[0] for name, values in parse_qs(urlsplit(link).query).items()}
        assert asked == {
            "schedule": str(ready.schedule.sysid),
            "day": today.isoformat(),
            "slot": "walk_in:" + rows["Ana Primeira"].starts_at.isoformat(),
            "arrived": "on",
        }
        # The search keeps where the page came from, and so does the choice of the patient.
        found = assert_safe(client.get(link + "&q=Maria"))
        chosen = re.search(r'href="(\?patient=[^"]+)"', found).group(1).replace("&amp;", "&")
        assert "arrived=on" in chosen and "slot=walk_in" in chosen
        html = assert_safe(client.get(url(ready, "book") + chosen))
        assert re.search(r'name="slot" value="walk_in:[^"]+" checked', html)
        assert re.search(r'name="arrived"[^>]*checked', html) and "Atendimento prioritário (Lei 10.048)" in html
        fields = {**asked, "patient": ready.patient.sysid, "appointment_type": ready.kind.sysid}
        response = client.post(url(ready, "book"), {**fields, "priority": "on", "idempotency_key": "now"})
        assert (response.status_code, response["Location"]) == (302, queue_page)
        assert waiting() == [(2, True), (3, True), (1, False)]
        html = client.get(queue_page).content.decode()
        assert "Consulta marcada. Chegada registrada: chegada nº 3." in html and "Maria Paciente Secreta" in html
        # The same form sent again finds the appointment as it is and numbers nobody.
        response = client.post(url(ready, "book"), {**fields, "priority": "on", "idempotency_key": "now"})
        assert response.status_code == 302 and waiting() == [(2, True), (3, True), (1, False)]
    with subtests.test("the arrival is of the day of the appointment"):
        other = new_patient(ready, full_name="Dora Quarta")
        fields = {
            "patient": other.sysid,
            "schedule": ready.schedule.sysid,
            "appointment_type": ready.kind.sysid,
            "day": (today + timedelta(days=7)).isoformat(),
            "slot": "walk_in:" + (rows["Ana Primeira"].starts_at + timedelta(days=7)).isoformat(),
        }
        response = client.post(url(ready, "book"), {**fields, "arrived": "on", "idempotency_key": "later"})
        assert response.status_code == 400 and "só é registrada no dia da consulta" in response.content.decode()
        assert booked(ready, other) == []
        # The mark alone is kept for the day the patient comes.
        response = client.post(url(ready, "book"), {**fields, "priority": "on", "idempotency_key": "later"})
        assert response.status_code == 302
        (row,) = booked(ready, other)
        assert detail(ready, row).is_priority and row.status == "scheduled"


def test_the_appointment_page_shows_the_period_and_corrects_the_priority(ready, subtests):
    set_grid(ready, walk_in(), AFTERNOON, walk_in(weekday=1))
    appointment = arrive(ready, "a")
    client = client_for(ready.a.reception)
    page = url(ready, "appointment", appointment.sysid)

    def mark(value, who=client, revision=None, follow=False):
        fields = {"revision": revision or detail(ready, appointment).appointment.revision}
        if value:
            fields["priority"] = "on"
        return who.post(url(ready, "priority", appointment.sysid), fields, follow=follow)

    with subtests.test("the period in the place of a time"):
        html = assert_safe(client.get(page))
        assert "Ordem de chegada · 08:00–12:00" in html and "O paciente ainda não chegou." in html
        assert "Sem prioridade" in html and "Marcar como prioritário" in html
        assert url(ready, "queue", ready.schedule.sysid, ready.monday.isoformat()) in html
        assert "30 min" in html
    with subtests.test("the priority is set and taken off, with CAS"):
        assert mark(True).status_code == 302 and detail(ready, appointment).is_priority
        html = assert_safe(client.get(page))
        assert "Atendimento prioritário marcado." in html and "Tirar a prioridade" in html
        stale = mark(False, revision=1, follow=True)
        assert "mudou desde que a página abriu" in stale.content.decode() and detail(ready, appointment).is_priority
    with subtests.test("who only reads the schedule sees the mark and does not change it"):
        reader = let_finance_read(ready)
        html = assert_safe(reader.get(page))
        assert "Prioritário" in html and "Tirar a prioridade" not in html
        assert mark(False, who=reader).status_code == 404 and detail(ready, appointment).is_priority
    with subtests.test("moved to the session of another day, and to a time"):
        tuesday = ready.monday + timedelta(days=1)
        current = detail(ready, appointment).appointment
        tuesday_session = "walk_in:" + at(ready, 8, day=tuesday).isoformat()
        html = assert_safe(client.get(page, {"day": tuesday.isoformat()}))
        sessions = re.findall(r'name="slot" value="walk_in:([^"]+)"', html)
        # The walk-in period is a choice of the same picker.
        assert [datetime.fromisoformat(value) for value in sessions] == [at(ready, 8, day=tuesday)]
        response = client.post(
            url(ready, "reschedule", appointment.sysid),
            {"day": tuesday.isoformat(), "slot": tuesday_session, "revision": current.revision},
        )
        assert response.status_code == 302
        moved = detail(ready, appointment).appointment
        assert (moved.mode, moved.starts_at) == ("walk_in", at(ready, 8, day=tuesday))
        response = client.post(
            url(ready, "reschedule", appointment.sysid),
            {"day": ready.monday.isoformat(), "slot": at(ready, 14).isoformat(), "revision": moved.revision},
        )
        assert response.status_code == 302
        timed = detail(ready, appointment).appointment
        assert (timed.mode, timed.starts_at, timed.ends_at) == ("booked", at(ready, 14), at(ready, 14, 30))
        html = assert_safe(client.get(page))
        text = re.sub(r"<[^>]+>", "", html)  # The times are <time> elements (#122).
        assert "Chegada nº" not in html and "14:00–14:30" in text
        response = client.post(
            url(ready, "reschedule", appointment.sysid),
            {
                "day": ready.monday.isoformat(),
                "slot": "walk_in:" + at(ready, 8).isoformat(),
                "revision": timed.revision,
            },
        )
        assert response.status_code == 302 and detail(ready, appointment).appointment.mode == "walk_in"
    with subtests.test("after the arrival: the number, and the appointment is no longer moved"):
        current = detail(ready, appointment).appointment
        response = client.post(url(ready, "transition", appointment.sysid, "check_in"), {"revision": current.revision})
        assert response.status_code == 302 and response["Location"] == page
        html = assert_safe(client.get(page))
        assert "Chegada registrada: chegada nº 1." in html and "reschedule-heading" not in html
        assert re.search(r"<dt>Chegada nº</dt><dd>1</dd>", html) and "Tirar a prioridade" in html
        assert mark(False).status_code == 302 and not detail(ready, appointment).is_priority
