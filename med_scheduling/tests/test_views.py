"""Pages of the scheduling app: booking and attendance through the screens, authorization, safe HTML."""

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from applications.med_patients.service_api import PatientService

from ..service_api import AvailabilityRuleInput, ScheduleTypeInput, SchedulingService
from .booking import SP, at, book, prepare

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
UNSAFE = re.compile(r"\sstyle=|\son[a-z]+=", re.IGNORECASE)
APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_scheduling:{name}", args=((organization or ready.org_a).pk, *args))


def assert_safe(response):
    assert response.status_code == 200, response.status_code
    html = response.content.decode()
    assert not INLINE_SCRIPT.search(html), "inline script"
    assert not UNSAFE.search(html), "style= or on*= attribute"
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert "·" in title
    return html


def detail(ready, appointment_id, user=None):
    with ready.as_user(user or ready.a.reception) as actor:
        return SchedulingService().appointment(actor=actor, appointment_id=appointment_id).appointment


def test_pages_use_only_the_services():
    source = (APP_DIR / "views.py").read_text(encoding="utf-8")
    assert ".objects" not in source and "authorized_queryset" not in source and "from .services" not in source
    # Every page is on the practice's clock: none takes the core's decorator directly.
    assert "@tenant_page" not in source and source.count("@practice_page") >= 23


def test_every_page_renders_safe_html(ready, subtests):
    appointment = book(ready, 9)
    client = client_for(ready.a.admin)
    pages = {
        "day": url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}",
        "week": url(ready, "week", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}",
        "book": url(ready, "book") + f"?patient={ready.patient.sysid}",
        "appointment": url(ready, "appointment", appointment.sysid),
        "reception": url(ready, "reception"),
        "queue": url(ready, "queue", ready.schedule.sysid, ready.monday.isoformat()),
        "waitlist": url(ready, "waitlist"),
        "settings": url(ready, "settings"),
        "type-edit": url(ready, "type-edit", ready.kind.sysid),
        "schedules": url(ready, "schedules"),
        "schedule": url(ready, "schedule", ready.schedule.sysid),
        "period-edit": url(ready, "period-edit", ready.schedule.sysid, grid(ready)[0].sysid),
        "day-exception": url(ready, "day-exception", ready.schedule.sysid) + f"?date={ready.monday:%Y-%m-%d}",
        "setup": url(ready, "setup"),
        "patient_section": url(ready, "patient_section", ready.patient.sysid),
    }
    for name, address in pages.items():
        with subtests.test(page=name):
            assert_safe(client.get(address))


def test_book_and_attend_through_the_pages(ready):
    client = client_for(ready.a.reception)
    query = {
        "patient": ready.patient.sysid,
        "schedule": ready.schedule.sysid,
        "appointment_type": ready.kind.sysid,
        "day": ready.monday.isoformat(),
    }
    html = assert_safe(client.get(url(ready, "book"), query))
    offered = {datetime.fromisoformat(value): value for value in re.findall(r'name="slot" value="([^"]+)"', html)}
    slot = offered[at(ready, 10)]
    response = client.post(
        url(ready, "book"), {**query, "slot": slot, "payment_kind": "private", "idempotency_key": "page-book"}
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (row,) = SchedulingService().appointments(actor=actor, patient_id=ready.patient.sysid).items
    assert row.starts_at == at(ready, 10)

    page = assert_safe(client.get(url(ready, "appointment", row.sysid)))
    assert "Maria Paciente Secreta" in page and "Registrar chegada" in page

    for name in ("confirm", "check_in"):
        current = detail(ready, row.sysid)
        response = client.post(url(ready, "transition", row.sysid, name), {"revision": current.revision})
        assert response.status_code == 302
    assert detail(ready, row.sysid).status == "arrived"
    reception = assert_safe(client.get(url(ready, "reception")))
    assert "Maria Paciente Secreta" in reception or "Aguardando" in reception

    stale = client.post(url(ready, "transition", row.sysid, "start"), {"revision": 1}, follow=True)
    assert "mudou desde que a página abriu" in stale.content.decode()
    assert detail(ready, row.sysid).status == "arrived"

    # #119: cancelling asks first, with the reason on the confirmation page; the GET changes nothing.
    asked = assert_safe(client.get(url(ready, "cancel", row.sysid)))
    assert "Cancelar a consulta" in asked and 'name="reason"' in asked and "Maria Paciente Secreta" in asked
    assert detail(ready, row.sysid).status == "arrived"
    unexplained = client.post(
        url(ready, "cancel", row.sysid), {"reason": "", "revision": detail(ready, row.sysid).revision}
    )
    assert unexplained.status_code == 400 and detail(ready, row.sysid).status == "arrived"
    current = detail(ready, row.sysid)
    response = client.post(
        url(ready, "cancel", row.sysid), {"reason": "patient", "note": "", "revision": current.revision}
    )
    assert response.status_code == 302
    assert detail(ready, row.sysid).status == "cancelled"
    assert client.get(url(ready, "cancel", row.sysid)).status_code == 404  # Nothing left to cancel.


def test_final_transitions_ask_first(ready):
    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    page = assert_safe(client.get(url(ready, "appointment", appointment.sysid)))
    no_show = url(ready, "transition", appointment.sysid, "mark_no_show")
    # A future appointment cannot be a no-show yet: the page does not offer it, the confirmation is 404.
    assert no_show not in page and client.get(no_show).status_code == 404
    assert client.get(url(ready, "transition", appointment.sysid, "confirm")).status_code == 405
    for name in ("confirm", "check_in", "start"):
        current = detail(ready, appointment.sysid)
        assert (
            client.post(url(ready, "transition", appointment.sysid, name), {"revision": current.revision}).status_code
            == 302
        )
    complete = url(ready, "transition", appointment.sysid, "complete")
    assert f'href="{complete}"' in assert_safe(client.get(url(ready, "appointment", appointment.sysid)))
    asked = assert_safe(client.get(complete))
    assert "Concluir a consulta" in asked and "não volta atrás" in asked
    assert detail(ready, appointment.sysid).status == "in_progress"
    outsider = client_for(ready.b.reception)
    assert (
        outsider.get(url(ready, "transition", appointment.sysid, "complete", organization=ready.org_b)).status_code
        == 404
    )
    assert client.post(complete, {"revision": detail(ready, appointment.sysid).revision}).status_code == 302
    assert detail(ready, appointment.sysid).status == "completed"


def test_reschedule_through_the_page(ready):
    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    response = client.post(
        url(ready, "reschedule", appointment.sysid),
        {"day": ready.monday.isoformat(), "time": "11:00", "revision": appointment.revision},
    )
    assert response.status_code == 302
    assert detail(ready, appointment.sysid).starts_at == at(ready, 11)


def test_unknown_transition_and_other_organization_answer_404(ready):
    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    assert client.post(url(ready, "transition", appointment.sysid, "delete"), {"revision": 1}).status_code == 404
    outsider = client_for(ready.b.reception)
    assert outsider.get(url(ready, "appointment", appointment.sysid, organization=ready.org_b)).status_code == 404
    assert outsider.get(url(ready, "schedule", ready.schedule.sysid, organization=ready.org_b)).status_code == 404


def test_actor_without_schedule_grant_does_not_see_it(ready):
    book(ready, 9)
    client = client_for(ready.a.finance)
    html = assert_safe(client.get(url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"))
    assert "Agenda da Dra. Ana" not in html and "Maria Paciente Secreta" not in html


def test_reader_of_the_schedule_without_the_patient_sees_the_code_only(ready):
    appointment = book(ready, 9)
    with ready.as_user(ready.a.admin) as admin:
        SchedulingService().set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            writer_user_ids=(),
            expected_revision=SchedulingService().schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
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
    html = assert_safe(client_for(ready.a.finance).get(url(ready, "appointment", appointment.sysid)))
    assert "Paciente não disponível" in html and "Maria Paciente Secreta" not in html


def test_patient_page_tab_lists_the_appointments(ready):
    book(ready, 9)
    client = client_for(ready.a.reception)
    patient_page = client.get(reverse("med_patients:detail", args=(ready.org_a.pk, ready.patient.sysid)))
    assert url(ready, "patient_section", ready.patient.sysid) in patient_page.content.decode()
    html = assert_safe(client.get(url(ready, "patient_section", ready.patient.sysid)))
    assert "Agendada" in html or "Consulta" in html
    with ready.as_user(ready.a.reception) as actor:
        timeline = PatientService().timeline(actor=actor, patient_id=ready.patient.sysid).items
    assert [entry.title for entry in timeline if entry.source == "med_scheduling.appointments"] == ["Consulta agendada"]


def test_calendar_title_never_shows_the_patient(ready):
    appointment = book(ready, 9)
    from skeleton.contrib.calendar.service_api import CalendarService

    with ready.as_user(ready.a.reception) as actor:
        event = CalendarService().managed_event(
            actor=actor, source_app="med_scheduling", source_key=str(appointment.sysid)
        )
    assert "Maria" not in event.title and appointment.code in event.title


def test_day_page_query_count_does_not_grow(ready):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client = client_for(ready.a.reception)
    address = url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"

    def count():
        # The core rereads the instance appearance at most every few seconds per process, so one of
        # two back-to-back requests may carry that read; the smaller count is the page's own.
        sizes = []
        for _ in range(2):
            with CaptureQueriesContext(connection) as context:
                assert client.get(address).status_code == 200
            sizes.append(len(context))
        return min(sizes)

    book(ready, 8)
    client.get(address)
    one = count()
    for hour, minute in ((8, 30), (9, 0), (9, 30), (10, 0), (10, 30), (11, 0)):
        book(ready, hour, minute)
    assert count() == one


def test_the_appointment_takes_the_color_of_its_type(ready, subtests, monkeypatch):
    from datetime import time

    from django.utils import timezone

    from skeleton.service_api import NotFound

    service = SchedulingService()
    with ready.as_user(ready.a.admin) as admin:
        green = service.add_appointment_type(
            actor=admin, code="retorno", name="Retorno", duration_minutes=30, color="green", idempotency_key="green"
        )
    blue = book(ready, 9)
    noon_today = datetime.combine(timezone.localdate(timezone=SP), time(12), tzinfo=SP)  # the practice's day
    booked = {}
    with ready.as_user(ready.a.reception) as actor:
        for key, starts_at, fit_in in (("monday", at(ready, 10), False), ("today", noon_today, True)):
            booked[key] = service.book(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                patient_id=ready.patient.sysid,
                appointment_type_id=green.sysid,
                starts_at=starts_at,
                fit_in=fit_in,
                idempotency_key=f"green-{key}",
            )
    with ready.as_user(ready.a.admin) as admin:
        # A kind that left the list keeps colouring the appointments already booked with it.
        service.update_appointment_type(
            actor=admin, type_id=green.sysid, changes=(("is_active", False),), expected_revision=green.revision
        )
    client = client_for(ready.a.reception)

    def colors(address):
        html = assert_safe(client.get(address))
        return {link: color for color, link in re.findall(r'appt-color-([a-z]+)"><a href="([^"]+)"', html)}

    def link(appointment):
        return url(ready, "appointment", appointment.sysid)

    day = url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"
    week = url(ready, "week", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}"
    for name, address in (("day", day), ("week", week)):
        with subtests.test(page=name):
            found = colors(address)
            assert (found[link(blue)], found[link(booked["monday"])]) == ("blue", "green")
    with subtests.test(page="reception"):
        assert colors(url(ready, "reception"))[link(booked["today"])] == "green"
    with subtests.test("kinds the actor cannot read fall back to gray"):

        def unreadable(self, **_arguments):
            raise NotFound()

        monkeypatch.setattr(SchedulingService, "appointment_types", unreadable)
        assert set(colors(day).values()) == {"gray"}


def test_start_and_complete_through_the_pages(ready):
    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    for name, status in (("check_in", "arrived"), ("start", "in_progress"), ("complete", "completed")):
        current = detail(ready, appointment.sysid)
        response = client.post(url(ready, "transition", appointment.sysid, name), {"revision": current.revision})
        assert response.status_code == 302
        assert detail(ready, appointment.sysid).status == status
    page = assert_safe(client.get(url(ready, "appointment", appointment.sysid)))
    assert "Concluir" not in page and "Cancelar consulta" not in page


def test_waitlist_add_and_book_from_it_through_the_pages(ready):
    client = client_for(ready.a.reception)
    response = client.post(
        url(ready, "waitlist"),
        {
            "patient_code": ready.patient.code,
            "appointment_type": ready.kind.sysid,
            "preferred_period": "any",
            "earliest_date": ready.monday.isoformat(),
            "priority": "high",
            "note": "",
            "idempotency_key": "page-wait",
        },
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (entry,) = SchedulingService().waitlist(actor=actor).items
    page = assert_safe(client.get(url(ready, "waitlist")))
    assert f"entry={entry.sysid}" in page

    query = {
        "patient": ready.patient.sysid,
        "entry": entry.sysid,
        "revision": entry.revision,
        "schedule": ready.schedule.sysid,
        "appointment_type": ready.kind.sysid,
        "day": ready.monday.isoformat(),
    }
    html = assert_safe(client.get(url(ready, "book"), query))
    offered = {datetime.fromisoformat(value): value for value in re.findall(r'name="slot" value="([^"]+)"', html)}
    response = client.post(url(ready, "book"), {**query, "slot": offered[at(ready, 11)], "idempotency_key": "w-1"})
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        assert SchedulingService().waitlist(actor=actor).items == ()
        (row,) = SchedulingService().appointments(actor=actor, patient_id=ready.patient.sysid).items
    assert row.starts_at == at(ready, 11)


# ------------------------------------------------------ kinds: payment, schedule and duration


def add_kind(ready, code="unimed", name="Unimed", **values):
    values.setdefault("duration_minutes", 20)
    values.setdefault("payment_kind", "insurance")
    with ready.as_user(ready.a.admin) as admin:
        return SchedulingService().add_appointment_type(
            actor=admin, code=code, name=name, idempotency_key=code, **values
        )


def kinds(ready):
    with ready.as_user(ready.a.admin) as admin:
        return {kind.code: kind for kind in SchedulingService().appointment_types(actor=admin, active_only=False)}


def schedule_kinds(ready):
    """(kind, duration in force, own duration) of each kind the schedule was configured with."""
    with ready.as_user(ready.a.reception) as actor:
        taken = SchedulingService().schedule_types(actor=actor, schedule_id=ready.schedule.sysid)
    return [(item.appointment_type_id, item.duration_minutes, item.own_duration) for item in taken if item.configured]


def schedule_revision(ready):
    with ready.as_user(ready.a.reception) as actor:
        return SchedulingService().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision


def take(ready, *types):
    """Configure the schedule with (kind, own duration or None) pairs, or ScheduleTypeInput as they are."""
    revision = schedule_revision(ready)
    wanted = tuple(
        item if isinstance(item, ScheduleTypeInput) else ScheduleTypeInput(item[0].sysid, item[1]) for item in types
    )
    with ready.as_user(ready.a.reception) as actor:
        SchedulingService().set_schedule_types(
            actor=actor, schedule_id=ready.schedule.sysid, types=wanted, expected_revision=revision
        )


def offered_kinds(html):
    select = re.search(r'<select name="appointment_type".*?</select>', html, re.S).group(0)
    return [label.strip() for label in re.findall(r"<option[^>]*>([^<]+)</option>", select)]


def duration_shown(html):
    field = next(
        tag for tag in re.findall(r"<input[^>]*>", html) if 'name="duration"' in tag and 'type="number"' in tag
    )
    return re.search(r'value="(\d+)"', field).group(1)


def offered_slots(html):
    return {datetime.fromisoformat(value) for value in re.findall(r'name="slot" value="([^"]+)"', html)}


def booked(ready):
    with ready.as_user(ready.a.reception) as actor:
        return list(SchedulingService().appointments(actor=actor, patient_id=ready.patient.sysid).items)


def test_a_kind_is_added_and_changed_through_the_settings_pages(ready, subtests):
    client = client_for(ready.a.reception)
    with subtests.test("added with how it is paid for"):
        response = client.post(
            url(ready, "settings"),
            {
                "form": "type",
                "type-code": "unimed",
                "type-name": "Unimed",
                "type-duration_minutes": "20",
                "type-payment_kind": "insurance",
                "type-color": "green",
                "type-billing_code": "",
                "idempotency_key": "page-type",
            },
        )
        assert response.status_code == 302
        assert kinds(ready)["unimed"].payment_kind == "insurance"
    kind = kinds(ready)["unimed"]
    edit = url(ready, "type-edit", kind.sysid)
    with subtests.test("the list shows the payment and the way to the edit page"):
        html = assert_safe(client.get(url(ready, "settings")))
        assert "Convênio" in html and edit in html
    with subtests.test("the edit page comes filled"):
        html = assert_safe(client.get(edit))
        assert 'value="Unimed"' in html and 'value="insurance" selected' in html and 'name="code"' not in html
    values = {
        "name": "Unimed Retorno",
        "duration_minutes": "15",
        "payment_kind": "courtesy",
        "color": "teal",
        "billing_code": "U1",
        "is_active": "on",
    }
    with subtests.test("changed"):
        assert client.post(edit, {**values, "revision": kind.revision}).status_code == 302
        saved = kinds(ready)["unimed"]
        assert (saved.name, saved.duration_minutes, saved.payment_kind, saved.color, saved.billing_code) == (
            "Unimed Retorno",
            15,
            "courtesy",
            "teal",
            "U1",
        )
        assert saved.is_active and saved.code == "unimed"
    with subtests.test("a duration out of range shows the error and changes nothing"):
        current = kinds(ready)["unimed"]
        response = client.post(edit, {**values, "duration_minutes": "4", "revision": current.revision})
        assert response.status_code == 400 and kinds(ready)["unimed"] == current
    with subtests.test("a page that opened before another change saves nothing"):
        current = kinds(ready)["unimed"]
        response = client.post(edit, {**values, "name": "Velho", "revision": kind.revision}, follow=True)
        assert "mudou desde que a página abriu" in response.content.decode()
        assert kinds(ready)["unimed"] == current
    with subtests.test("deactivated"):
        current = kinds(ready)["unimed"]
        inactive = {name: value for name, value in values.items() if name != "is_active"}
        assert client.post(edit, {**inactive, "revision": current.revision}).status_code == 302
        assert not kinds(ready)["unimed"].is_active
        assert "Inativo" in assert_safe(client.get(url(ready, "settings")))
    with subtests.test("who only reads the practice does not change a kind"):
        reader = client_for(ready.a.doctor)
        current = kinds(ready)["unimed"]
        assert edit not in assert_safe(reader.get(url(ready, "settings")))
        assert reader.get(edit).status_code == 404
        assert reader.post(edit, {**values, "revision": current.revision}).status_code == 404
        assert kinds(ready)["unimed"] == current
    with subtests.test("another organization and an unknown kind"):
        outsider = client_for(ready.b.reception)
        assert outsider.get(url(ready, "type-edit", kind.sysid, organization=ready.org_b)).status_code == 404
        assert client.get(url(ready, "type-edit", uuid4())).status_code == 404


def test_the_kinds_of_a_schedule_are_chosen_on_its_page(ready, subtests):
    insured = add_kind(ready)
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)
    on, minutes = f"types-on_{insured.sysid.hex}", f"types-minutes_{insured.sysid.hex}"
    # The two modes come ticked on the page; their own cases are in test_walk_in_views.
    modes = {f"types-booked_{insured.sysid.hex}": "on", f"types-walk_in_{insured.sysid.hex}": "on"}

    def save(who=client, revision=None, **fields):
        fields = {"form": "types", "revision": revision or schedule_revision(ready), **fields}
        return who.post(page, fields, follow=True)

    with subtests.test("without configuration the schedule takes every kind"):
        html = assert_safe(client.get(page))
        assert "Esta agenda atende todos os tipos de atendimento ativos" in html
        assert re.search(r'name="types-scope" value="all"[^>]*checked', html)
    with subtests.test("the ticked kinds with the duration of the schedule"):
        response = save(**{"types-scope": "chosen", on: "on", minutes: "40", **modes})
        assert response.status_code == 200 and "Tipos de atendimento da agenda salvos" in response.content.decode()
        assert schedule_kinds(ready) == [(insured.sysid, 40, 40)]
        html = assert_safe(client.get(page))
        assert "Esta agenda atende todos" not in html and "Duração desta agenda" in html
        assert re.search(rf'name="{on}"[^>]*checked', html) and re.search(rf'name="{minutes}"[^>]*value="40"', html)
        assert re.search(r'name="types-scope" value="chosen"[^>]*checked', html)
    with subtests.test("only the ticked ones, with none ticked"):
        response = save(**{"types-scope": "chosen"})
        assert response.status_code == 400 and "Marque ao menos um tipo de atendimento" in response.content.decode()
    with subtests.test("a duration out of range"):
        assert save(**{"types-scope": "chosen", on: "on", minutes: "4", **modes}).status_code == 400
    with subtests.test("a page that opened before another change saves nothing"):
        response = save(revision=1, **{"types-scope": "all"})
        assert "A agenda mudou desde que a página abriu" in response.content.decode()
    assert schedule_kinds(ready) == [(insured.sysid, 40, 40)]
    with subtests.test("who only reads the schedule sees the kinds and does not change them"):
        with ready.as_user(ready.a.admin) as admin:
            SchedulingService().set_schedule_access(
                actor=admin,
                schedule_id=ready.schedule.sysid,
                writer_group_ids=(ready.a.groups["reception"],),
                reader_group_ids=(ready.a.groups["finance"],),
                writer_user_ids=(),
                expected_revision=SchedulingService().schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
            )
        reader = client_for(ready.a.finance)
        html = assert_safe(reader.get(page))
        assert "Tipos atendidos nesta agenda" in html and "Unimed" in html and 'value="types"' not in html
        assert save(who=reader, **{"types-scope": "all"}).status_code == 404
        assert schedule_kinds(ready) == [(insured.sysid, 40, 40)]
    with subtests.test("another organization"):
        outsider = client_for(ready.b.reception)
        address = url(ready, "schedule", ready.schedule.sysid, organization=ready.org_b)
        assert outsider.post(address, {"form": "types", "revision": 1, "types-scope": "all"}).status_code == 404
    with subtests.test("the professional of the schedule puts it back to every kind"):
        assert save(who=client_for(ready.a.doctor), **{"types-scope": "all"}).status_code == 200
        assert schedule_kinds(ready) == []


def test_booking_offers_the_kinds_of_the_schedule_with_the_suggested_duration(ready, subtests):
    insured = add_kind(ready)
    take(ready, (insured, 40))
    client = client_for(ready.a.reception)
    base = {"patient": ready.patient.sysid}
    query = {
        **base,
        "schedule": ready.schedule.sysid,
        "appointment_type": insured.sysid,
        "day": ready.monday.isoformat(),
    }

    with subtests.test("before any choice: the kinds of the schedule and the duration of the first"):
        html = assert_safe(client.get(url(ready, "book"), base))
        assert offered_kinds(html) == ["Unimed · 40 min"] and duration_shown(html) == "40"
        assert 'name="slot"' not in html
    with subtests.test("the free slots are the ones the suggested duration fits"):
        html = assert_safe(client.get(url(ready, "book"), query))
        slots = offered_slots(html)
        assert at(ready, 11) in slots and at(ready, 11, 30) not in slots
        assert duration_shown(html) == "40" and "Convênio" in html
    with subtests.test("a typed duration is kept and the slots follow it"):
        html = assert_safe(client.get(url(ready, "book"), {**query, "duration": "90", "suggested_duration": "40"}))
        slots = offered_slots(html)
        assert at(ready, 10, 30) in slots and at(ready, 11) not in slots
        assert duration_shown(html) == "90" and "o padrão é 40 min" in html
    with subtests.test("a duration out of range shows the error and no slot"):
        response = client.get(url(ready, "book"), {**query, "duration": "500", "suggested_duration": "40"})
        html = assert_safe(response)
        assert 'name="slot"' not in html and "error-summary" in html
    take(ready, (insured, 40), (ready.kind, None))
    with subtests.test("an untouched suggestion follows the kind"):
        asked = {**query, "appointment_type": ready.kind.sysid, "duration": "40", "suggested_duration": "40"}
        html = assert_safe(client.get(url(ready, "book"), asked))
        assert offered_kinds(html) == ["Consulta · 30 min", "Unimed · 40 min"]
        assert duration_shown(html) == "30" and at(ready, 11, 30) in offered_slots(html)
    take(ready, (insured, 40))
    with subtests.test("a kind the schedule does not take"):
        asked = {**query, "appointment_type": ready.kind.sysid}
        html = assert_safe(client.get(url(ready, "book"), asked))
        assert "Esta agenda não atende este tipo de atendimento" in html and 'name="slot"' not in html
        response = client.post(
            url(ready, "book"), {**asked, "slot": at(ready, 9).isoformat(), "idempotency_key": "refused"}
        )
        assert response.status_code == 400 and booked(ready) == []
    with subtests.test("booked with the typed duration and paid for as the kind says"):
        typed = {"duration": "50", "suggested_duration": "40", "slot": at(ready, 9).isoformat()}
        response = client.post(url(ready, "book"), {**query, **typed, "idempotency_key": "typed"})
        assert response.status_code == 302
        (row,) = booked(ready)
        assert (row.appointment_type_id, row.payment_kind) == (insured.sysid, "insurance")
        assert (row.starts_at, row.ends_at) == (at(ready, 9), at(ready, 9, 50))
    with subtests.test("booked without a duration: the one of the schedule for the kind"):
        response = client.post(
            url(ready, "book"), {**query, "slot": at(ready, 10).isoformat(), "idempotency_key": "suggested"}
        )
        assert response.status_code == 302
        latest = max(booked(ready), key=lambda row: row.starts_at)
        assert (latest.starts_at, latest.ends_at) == (at(ready, 10), at(ready, 10, 40))
    with subtests.test("a kind the schedule takes only by order of arrival has no free time"):
        take(ready, ScheduleTypeInput(insured.sysid, allow_booked=False))
        html = assert_safe(client.get(url(ready, "book"), {**query, "duration": "", "suggested_duration": ""}))
        assert offered_kinds(html) == ["Unimed · 20 min"] and offered_slots(html) == set()
        assert "A agenda não atende Unimed com hora marcada." in html


def test_booking_from_the_waitlist_keeps_the_kind_of_the_entry(ready):
    add_kind(ready)
    with ready.as_user(ready.a.reception) as actor:
        entry = SchedulingService().add_to_waitlist(
            actor=actor,
            patient_id=ready.patient.sysid,
            appointment_type_id=ready.kind.sysid,
            earliest_date=ready.monday,
            idempotency_key="entry",
        )
    client = client_for(ready.a.reception)
    query = {
        "patient": ready.patient.sysid,
        "entry": entry.sysid,
        "revision": entry.revision,
        "appointment_type": ready.kind.sysid,
    }
    html = assert_safe(client.get(url(ready, "book"), query))
    assert offered_kinds(html) == ["Consulta · 30 min"] and duration_shown(html) == "30"
    chosen = {
        "schedule": ready.schedule.sysid,
        "day": ready.monday.isoformat(),
        "duration": "45",
        "suggested_duration": "30",
        "slot": at(ready, 9).isoformat(),
    }
    response = client.post(url(ready, "book"), {**query, **chosen, "idempotency_key": "from-the-list"})
    assert response.status_code == 302
    (row,) = booked(ready)
    assert (row.appointment_type_id, row.ends_at) == (ready.kind.sysid, at(ready, 9, 45))


# ------------------------------------------------------ the weekly grid: periods and their kinds

MONDAY_MORNING = (0, 480, 720, ())


def grid(ready):
    with ready.as_user(ready.a.reception) as actor:
        return SchedulingService().availability(actor=actor, schedule_id=ready.schedule.sysid)


def shapes(ready):
    return [(rule.weekday, rule.start_minute, rule.end_minute, rule.appointment_type_ids) for rule in grid(ready)]


def let_finance_read(ready):
    """Finance reads the schedule and does not write it."""
    with ready.as_user(ready.a.admin) as admin:
        SchedulingService().set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            writer_user_ids=(),
            expected_revision=SchedulingService().schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
        )
    return client_for(ready.a.finance)


def test_the_weekly_grid_is_built_on_the_page_of_the_schedule(ready, subtests):
    insured = add_kind(ready)
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)
    (monday,) = grid(ready)

    def add(who=client, revision=None, **fields):
        fields = {f"periods-{name}": value for name, value in {"valid_from": "2026-01-01", **fields}.items()}
        return who.post(page, {"form": "periods", "revision": revision or schedule_revision(ready), **fields})

    with subtests.test("the week is shown by weekday, with what each period takes"):
        html = assert_safe(client.get(page))
        assert "Grade semanal" in html and "08:00–12:00" in html and "Todos os tipos da agenda" in html
        assert [
            day
            for day in ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
            if f">{day}</h3>" in html
        ] == [
            "Segunda",
            "Terça",
            "Quarta",
            "Quinta",
            "Sexta",
            "Sábado",
            "Domingo",
        ]
        assert html.count("Sem atendimento") == 6
        assert url(ready, "period-edit", ready.schedule.sysid, monday.sysid) in html
    with subtests.test("one period on several weekdays at once, with its kinds"):
        response = add(weekdays=["1", "3"], start_1="14:00", end_1="18:00", kinds=[str(insured.sysid)])
        assert response.status_code == 302
        assert shapes(ready) == [
            MONDAY_MORNING,
            (1, 840, 1080, (insured.sysid,)),
            (3, 840, 1080, (insured.sysid,)),
        ]
        assert grid(ready)[0] == monday
        html = assert_safe(client.get(page))
        assert "Períodos incluídos na grade semanal" in html and html.count("14:00–18:00") >= 2
        assert html.count("Sem atendimento") == 4 and re.search(r"<p>\s*Unimed\s*</p>", html)
    with subtests.test("three periods on the same day"):
        response = add(
            weekdays=["4"],
            start_1="07:00",
            end_1="09:00",
            start_2="10:00",
            end_2="12:00",
            start_3="13:00",
            end_3="00:00",
        )
        assert response.status_code == 302
        assert [shape[1:3] for shape in shapes(ready) if shape[0] == 4] == [(420, 540), (600, 720), (780, 1440)]
        assert "13:00–24:00" in assert_safe(client.get(page))
    saved = shapes(ready)
    with subtests.test("a period over another shows the mistake on its field and keeps what was typed"):
        response = add(weekdays=["0", "2"], start_1="11:00", end_1="13:00", start_2="15:00", end_2="16:00")
        html = response.content.decode()
        assert response.status_code == 400
        assert "Segunda: 11:00–13:00 se sobrepõe ao período 08:00–12:00" in html
        assert 'href="#id_periods-start_1"' in html and 'href="#id_periods-start_2"' not in html
        assert re.search(r'name="periods-start_1"[^>]*value="11:00"', html)
        assert re.search(r'name="periods-end_2"[^>]*value="16:00"', html)
        assert re.search(r'name="periods-weekdays" value="2"[^>]*checked', html)
    with subtests.test("no weekday ticked"):
        response = add(start_1="14:00", end_1="18:00")
        assert response.status_code == 400 and "Marque ao menos um dia da semana" in response.content.decode()
        assert 'href="#id_periods-weekdays_0"' in response.content.decode()
    with subtests.test("an end before its start, and half a line"):
        assert add(weekdays=["5"], start_1="10:00", end_1="09:00").status_code == 400
        assert add(weekdays=["5"], start_1="10:00", end_1="11:00", start_2="12:00").status_code == 400
    with subtests.test("a kind the schedule does not take"):
        take(ready, (ready.kind, None))
        response = add(weekdays=["5"], start_1="10:00", end_1="11:00", kinds=[str(insured.sysid)])
        assert response.status_code == 400
        html = assert_safe(client.get(page))
        assert "a agenda não atende mais" in html and f'value="{insured.sysid}"' not in html
        take(ready)
    with subtests.test("a page that opened before another change saves nothing"):
        response = add(revision=1, weekdays=["5"], start_1="10:00", end_1="11:00")
        assert response.status_code == 302
        assert "A agenda mudou desde que a página abriu" in client.get(page).content.decode()
    assert shapes(ready) == saved
    with subtests.test("the professional of the schedule adds too"):
        assert add(who=client_for(ready.a.doctor), weekdays=["5"], start_1="10:00", end_1="11:00").status_code == 302
        assert (5, 600, 660, ()) in shapes(ready)
    saved = shapes(ready)
    with subtests.test("who only reads the schedule sees the week and changes nothing"):
        reader = let_finance_read(ready)
        html = assert_safe(reader.get(page))
        assert "Grade semanal" in html and "14:00–18:00" in html and "Unimed" in html
        assert 'value="periods"' not in html and "/periods/" not in html
        assert add(who=reader, weekdays=["6"], start_1="10:00", end_1="11:00").status_code == 404
    with subtests.test("another organization"):
        outsider = client_for(ready.b.reception)
        address = url(ready, "schedule", ready.schedule.sysid, organization=ready.org_b)
        fields = {"form": "periods", "revision": 1, "periods-weekdays": "6", "periods-valid_from": "2026-01-01"}
        assert (
            outsider.post(address, {**fields, "periods-start_1": "10:00", "periods-end_1": "11:00"}).status_code == 404
        )
    assert shapes(ready) == saved


def test_a_period_is_changed_and_removed_from_the_grid(ready, subtests):
    insured = add_kind(ready)
    client = client_for(ready.a.reception)
    page = url(ready, "schedule", ready.schedule.sysid)
    current = schedule_revision(ready)
    with ready.as_user(ready.a.reception) as actor:
        morning, afternoon = SchedulingService().set_availability(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            rules=(
                AvailabilityRuleInput(0, 8 * 60, 12 * 60, date(2026, 1, 1)),
                AvailabilityRuleInput(0, 14 * 60, 18 * 60, date(2026, 1, 1), date(2030, 12, 31)),
            ),
            expected_revision=current,
        )
    edit = url(ready, "period-edit", ready.schedule.sysid, morning.sysid)
    values = {"weekday": "0", "start": "08:00", "end": "12:00", "valid_from": "2026-01-01"}

    def change(who=client, address=edit, revision=None, **fields):
        return who.post(address, {**values, "revision": revision or schedule_revision(ready), **fields})

    def remove(rule, who=client, revision=None, **options):
        address = url(ready, "period-remove", ready.schedule.sysid, rule.sysid)
        return who.post(address, {"revision": revision or schedule_revision(ready)}, **options)

    with subtests.test("the page comes filled with the period"):
        html = assert_safe(client.get(edit))
        assert "Segunda, 08:00–12:00" in html and re.search(r'<option value="0"[^>]*selected', html)
        assert re.search(r'name="start"[^>]*value="08:00"', html) and re.search(r'name="end"[^>]*value="12:00"', html)
        assert re.search(r'name="valid_from"[^>]*value="2026-01-01"', html)
        assert not re.search(r'name="kinds"[^>]*checked', html)
        other = assert_safe(client.get(url(ready, "period-edit", ready.schedule.sysid, afternoon.sysid)))
        assert re.search(r'name="valid_until"[^>]*value="2030-12-31"', other)
    with subtests.test("the kinds change and the period is the same one"):
        assert change(kinds=[str(insured.sysid)]).status_code == 302
        first, second = grid(ready)
        assert (first.sysid, first.appointment_type_ids, second) == (morning.sysid, (insured.sysid,), afternoon)
        assert "Período salvo" in client.get(page).content.decode()
        assert re.search(r'name="kinds"[^>]*checked', assert_safe(client.get(edit)))
    with subtests.test("over another period of the day"):
        response = change(end="15:00", kinds=[str(insured.sysid)])
        html = response.content.decode()
        assert response.status_code == 400 and "se sobrepõe ao período 14:00–18:00" in html
        assert 'href="#id_start"' in html and re.search(r'name="end"[^>]*value="15:00"', html)
    with subtests.test("a page that opened before another change saves nothing"):
        response = change(revision=1, end="11:00")
        assert response.status_code == 302 and response["Location"] == page
        assert "A agenda mudou desde que a página abriu" in client.get(page).content.decode()
    assert shapes(ready) == [(0, 480, 720, (insured.sysid,)), (0, 840, 1080, ())]
    with subtests.test("a kind the schedule stopped taking leaves the period on saving"):
        take(ready, (ready.kind, None))
        html = assert_safe(client.get(edit))
        assert "tipos que a agenda não atende mais (Unimed)" in html and f'value="{insured.sysid}"' not in html
        assert change().status_code == 302
        assert grid(ready)[0].appointment_type_ids == () and grid(ready)[0].sysid == morning.sysid
        take(ready)
    with subtests.test("who only reads, another organization and an unknown period"):
        reader = let_finance_read(ready)
        outsider = client_for(ready.b.reception)
        foreign = url(ready, "period-edit", ready.schedule.sysid, morning.sysid, organization=ready.org_b)
        gone = url(ready, "period-edit", ready.schedule.sysid, uuid4())
        assert reader.get(edit).status_code == change(who=reader, end="11:00").status_code == 404
        assert outsider.get(foreign).status_code == outsider.post(foreign, {**values, "revision": 1}).status_code == 404
        assert client.get(gone).status_code == change(address=gone).status_code == 404
        assert remove(morning, who=reader).status_code == 404
        away = url(ready, "period-remove", ready.schedule.sysid, morning.sysid, organization=ready.org_b)
        assert outsider.post(away, {"revision": 1}).status_code == 404
        # #119: the GET is the confirmation; it changes nothing and names the period.
        asked = assert_safe(client.get(url(ready, "period-remove", ready.schedule.sysid, morning.sysid)))
        assert "Remover o período da grade" in asked and "btn-danger" in asked
        assert reader.get(url(ready, "period-remove", ready.schedule.sysid, morning.sysid)).status_code == 404
    assert shapes(ready) == [(0, 480, 720, ()), (0, 840, 1080, ())]
    with subtests.test("other hours make another period, and the old address is gone"):
        assert change(weekday="2", start="09:00", end="11:00").status_code == 302
        assert shapes(ready) == [(0, 840, 1080, ()), (2, 540, 660, ())]
        assert client.get(edit).status_code == 404
    with subtests.test("removed with a revision that is not the current one"):
        response = remove(afternoon, revision=1, follow=True)
        assert "A agenda mudou desde que a página abriu" in response.content.decode() and len(grid(ready)) == 2
    with subtests.test("removed"):
        response = remove(afternoon, follow=True)
        assert "Período removido da grade semanal" in response.content.decode()
        assert shapes(ready) == [(2, 540, 660, ())]
    with subtests.test("removed twice"):
        response = remove(afternoon, follow=True)
        assert "Este período já não está na grade" in response.content.decode() and len(grid(ready)) == 1
    with subtests.test("the appointments booked in a period that left stay booked"):
        appointment = detail(ready, book(ready, 15, fit_in=True).sysid)
        (last,) = grid(ready)
        assert remove(last).status_code == 302 and grid(ready) == ()
        assert detail(ready, appointment.sysid).status == "scheduled"


def test_the_script_is_an_optional_static_file_bound_by_data_attributes(ready):
    client = client_for(ready.a.reception)
    script = re.compile(r'<script src="[^"]*med_scheduling/med_scheduling\.js" defer></script>')
    booking = assert_safe(client.get(url(ready, "book"), {"patient": ready.patient.sysid}))
    assert script.search(booking)
    select = re.search(r'<select name="appointment_type"[^>]*>', booking).group(0)
    assert f'data-kind-durations="{{&quot;{ready.kind.sysid}&quot;: 30}}"' in select
    assert 'data-duration="typed"' in booking and 'data-duration="suggested"' in booking
    schedule = assert_safe(client.get(url(ready, "schedule", ready.schedule.sysid)))
    assert script.search(schedule) and "data-period-lines" in schedule and 'data-add-label="' in schedule
    assert len(re.findall(r"<div class=\"period-line\" data-period-line data-empty>", schedule)) == 3
    day = assert_safe(client.get(url(ready, "day-exception", ready.schedule.sysid), {"date": ready.monday}))
    # Each period of the day is a scope of its own for the script: its mode folds its own "Vagas".
    assert script.search(day) and day.count("data-period-mode") == day.count("data-walk-in-only") == 4
    assert len(re.findall(r"<fieldset[^>]*data-period data-period-line", day)) == 4
    source = (APP_DIR / "static" / "med_scheduling" / "med_scheduling.js").read_text(encoding="utf-8")
    assert 'select.closest("[data-period]")' in source
    assert source.startswith('"use strict";')
    assert not re.search(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|fetch\(|XMLHttpRequest", source
    )


def test_day_page_query_count_does_not_grow_with_the_periods(ready):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    insured = add_kind(ready)
    client = client_for(ready.a.reception)
    address = url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}"

    def count():
        sizes = []
        for _ in range(2):
            with CaptureQueriesContext(connection) as context:
                assert client.get(address).status_code == 200
            sizes.append(len(context))
        return min(sizes)

    def save(*rules):
        revision = schedule_revision(ready)
        with ready.as_user(ready.a.reception) as actor:
            SchedulingService().set_availability(
                actor=actor, schedule_id=ready.schedule.sysid, rules=rules, expected_revision=revision
            )

    kinds = (insured.sysid, ready.kind.sysid)
    save(AvailabilityRuleInput(0, 480, 540, date(2026, 1, 1), appointment_type_ids=kinds))
    client.get(address)
    one = count()
    save(
        *(
            AvailabilityRuleInput(0, 480 + 60 * hour, 540 + 60 * hour, date(2026, 1, 1), appointment_type_ids=kinds)
            for hour in range(8)
        )
    )
    assert count() == one


def test_the_pages_follow_the_clock_of_the_practice_not_of_the_reader(ready, subtests, monkeypatch):
    """The reader's time zone is the instance's, UTC; the practice's is São Paulo, where 09:00 is 12:00 UTC."""
    appointment = book(ready, 9)
    client = client_for(ready.a.reception)
    monday = f"{ready.monday:%d/%m/%Y}"
    with subtests.test("the appointment"):
        html = assert_safe(client.get(url(ready, "appointment", appointment.sysid)))
        described = re.search(r'<p class="page-description">(.*?)</p>', html, re.S).group(1)
        described = re.sub(r"<[^>]+>", "", described)  # The day and the hours are each in a <time>.
        assert monday in described and "09:00–09:30" in described
    with subtests.test("the day, with its free hours"):
        html = assert_safe(client.get(url(ready, "day"), {"date": ready.monday.isoformat()}))
        hours = set(re.findall(r">(\d\d:\d\d)</time>", html))
        assert {"08:00", "09:00", "11:30"} <= hours and max(hours) == "11:30"
    with subtests.test("the week"):
        html = assert_safe(client.get(url(ready, "week", ready.schedule.sysid), {"start": ready.monday.isoformat()}))
        assert ">09:00</time>" in html and ">12:00</time>" not in html
    with subtests.test("the free hours of the booking page"):
        query = {
            "patient": ready.patient.sysid,
            "schedule": ready.schedule.sysid,
            "appointment_type": ready.kind.sysid,
            "day": ready.monday.isoformat(),
        }
        html = assert_safe(client.get(url(ready, "book"), query))
        offered = re.findall(r'name="slot" value="([^"]+)"[^>]*> <time[^>]*>(\d\d:\d\d)</time></label>', html)
        assert offered and all(
            f"{datetime.fromisoformat(value).astimezone(SP):%H:%M}" == label for value, label in offered
        )
    with subtests.test("today is the day of the practice"):
        # Tuesday 01:30 UTC is still Monday 22:30 at the practice.
        late = datetime.combine(ready.monday + timedelta(days=1), time(1, 30), tzinfo=UTC)
        monkeypatch.setattr("django.utils.timezone.now", lambda: late)
        client = client_for(ready.a.reception)
        html = assert_safe(client.get(url(ready, "day")))
        assert monday in html and ">09:00</time>" in html
        html = assert_safe(client.get(url(ready, "reception")))
        assert ">09:00</time>" in html and "Maria Paciente Secreta" in html


def test_the_pages_open_before_the_practice_is_set_up(clinic):
    client = client_for(clinic.a.admin)

    def address(name):
        return reverse(f"med_scheduling:{name}", args=(clinic.org_a.pk,))

    assert_safe(client.get(address("home")))
    assert_safe(client.get(address("setup")))
    response = client.get(address("day"))
    assert response.status_code == 302 and response["Location"] == address("home")


# ---------------------------------------------------------- the professional's schedule, calendars


def _professional(name, **extra):
    return {
        "form": "professional",
        "professional-display_name": name,
        "professional-council": "crm",
        "professional-council_number": "",
        "professional-council_state": "",
        "professional-specialty": "",
        "professional-member": "",
        "idempotency_key": f"page-{name}",
        **extra,
    }


def _professionals(ready):
    with ready.as_user(ready.a.admin) as actor:
        return {item.display_name: item for item in SchedulingService().professionals(actor=actor, active_only=False)}


def _schedules(ready, user=None):
    with ready.as_user(user or ready.a.admin) as actor:
        return {item.name: item for item in SchedulingService().schedules(actor=actor, active_only=False)}


def test_a_professional_is_registered_with_the_schedule_in_one_step(ready, subtests, monkeypatch):
    from skeleton.service_api import InvalidInput

    admin = client_for(ready.a.admin)
    settings = url(ready, "settings")
    with subtests.test("offered, already ticked, to who manages access"):
        html = assert_safe(admin.get(settings))
        box = re.search(r"<input[^>]*name=\"professional-create_schedule\"[^>]*>", html).group(0)
        assert "checked" in box and "Criar a agenda deste profissional" in html
        assert "professional-create_schedule" not in assert_safe(client_for(ready.a.reception).get(settings))
    with subtests.test("both are created, and the page goes to the schedule"):
        response = admin.post(
            settings,
            _professional(
                "Dr. Bruno", **{"professional-member": str(ready.a.finance.pk), "professional-create_schedule": "on"}
            ),
        )
        created = _schedules(ready)["Dr. Bruno"]
        assert response.status_code == 302 and response["Location"] == url(ready, "schedule", created.sysid)
        assert created.professional_id == _professionals(ready)["Dr. Bruno"].sysid
        # The professional's person owns the schedule: it is theirs to change, with no group granted.
        assert _schedules(ready, ready.a.finance)["Dr. Bruno"].writable
        assert "Dr. Bruno" not in _schedules(ready, ready.a.reception)
    with subtests.test("unticked, only the professional"):
        response = admin.post(settings, _professional("Dra. Carla"))
        assert response.status_code == 302 and response["Location"] == settings
        assert "Dra. Carla" in _professionals(ready) and "Dra. Carla" not in _schedules(ready)
    with subtests.test("who does not manage access gets no schedule by asking"):
        response = client_for(ready.a.reception).post(
            settings, _professional("Dr. Davi", **{"professional-create_schedule": "on"})
        )
        assert response.status_code == 302 and response["Location"] == settings
        assert "Dr. Davi" in _professionals(ready) and "Dr. Davi" not in _schedules(ready)
    with subtests.test("a schedule that fails takes the professional back"):

        def refuse(self, **kwargs):
            raise InvalidInput({"name": ["Agenda recusada no teste."]})

        monkeypatch.setattr(SchedulingService, "create_schedule", refuse)
        response = admin.post(settings, _professional("Dra. Elisa", **{"professional-create_schedule": "on"}))
        assert response.status_code == 400 and "Agenda recusada no teste." in response.content.decode()
        assert "Dra. Elisa" not in _professionals(ready)


def test_each_calendar_has_its_own_subscription_link(ready, subtests):
    organization = ready.org_a.pk
    calendar = ready.schedule.calendar_id
    subscribe = url(ready, "calendar-subscribe", calendar)
    page = reverse("skeleton_calendar:calendar-link", args=(organization, calendar))
    reception, doctor = client_for(ready.a.reception), client_for(ready.a.doctor)
    appointment = book(ready, 9, notes="queixa sigilosa")
    with subtests.test("on the page of the schedule"):
        html = assert_safe(reception.get(url(ready, "schedule", ready.schedule.sysid)))
        assert subscribe in html and "Assinar no celular" in html
    with subtests.test("it leads to the page of the core that gives the link of that calendar"):
        response = reception.get(subscribe)
        assert (response.status_code, response["Location"]) == (302, page)
        assert reception.get(page).status_code == 200
        assert reception.post(subscribe).status_code == 405
    with subtests.test("who does not read the schedule sees no link and gets a 404"):
        finance = client_for(ready.a.finance)
        assert finance.get(subscribe).status_code == 404
        assert finance.get(url(ready, "schedule", ready.schedule.sysid)).status_code == 404
        assert subscribe not in assert_safe(finance.get(url(ready, "schedules")))
    with subtests.test("organization B gets a 404 for a calendar of A"):
        other = client_for(ready.b.admin)
        assert other.get(url(ready, "calendar-subscribe", calendar, organization=ready.org_b)).status_code == 404
    # The link is made by the core, on its page: the app never sees it. Each person has their own.
    links = {}
    for name, client in (("doctor", doctor), ("reception", reception)):
        issued = client.post(page)
        assert issued.status_code == 201
        links[name] = issued.context["url"]
    with subtests.test("the owner of the schedule reads the kind and the code, never the patient"):
        feed = Client().get(links["doctor"])
        assert feed.status_code == 200 and feed["Content-Type"].startswith("text/calendar")
        body = feed.content.decode()
        assert f"Consulta · {appointment.code}" in body
        assert "Maria" not in body and "queixa sigilosa" not in body and str(ready.patient.sysid) not in body
    with subtests.test("a group taken out by the schedule stops receiving through the link, on the next request"):
        assert Client().get(links["reception"]).status_code == 200
        with ready.as_user(ready.a.admin) as admin:
            current = SchedulingService().schedule(actor=admin, schedule_id=ready.schedule.sysid)
            SchedulingService().set_schedule_access(
                actor=admin,
                schedule_id=current.sysid,
                writer_group_ids=(),
                reader_group_ids=(),
                expected_revision=current.revision,
            )
        assert Client().get(links["reception"]).status_code == 404
        assert reception.get(subscribe).status_code == 404
        # The owner keeps the schedule and the link.
        assert Client().get(links["doctor"]).status_code == 200


def test_the_core_pages_leave_the_calendar_of_a_schedule_to_the_schedule(ready, subtests, monkeypatch):
    from skeleton.contrib.calendar.service_api import CalendarService

    from .. import calendar_bridge

    organization = ready.org_a.pk
    admin = client_for(ready.a.admin)

    def unmarked(actor, *, schedule_id, idempotency_key, **values):
        created = CalendarService().create_shared_calendar(
            actor=actor, idempotency_key=f"old:{idempotency_key}", **values
        )
        return created.sysid

    def core(name, calendar_id):
        return reverse(f"skeleton_calendar:{name}", args=(organization, calendar_id))

    with subtests.test("the pages of the core refuse to rename, share or delete it"):
        for name in ("calendar-rename", "calendar-sharing", "calendar-delete"):
            assert admin.post(core(name, ready.schedule.calendar_id), {"name": "Outro"}).status_code == 409, name
        with ready.as_user(ready.a.reception) as actor:
            (entry,) = SchedulingService().calendars(actor=actor)
        assert entry.name == "Agenda da Dra. Ana"
    # A schedule created before the core had the marker: its calendar has no origin yet.
    with ready.as_user(ready.a.admin) as actor, monkeypatch.context() as patched:
        patched.setattr(calendar_bridge, "create_calendar", unmarked)
        room = SchedulingService().add_room(actor=actor, name="Sala 1", idempotency_key="room")
        SchedulingService().create_schedule(
            actor=actor,
            name="Sala antiga",
            room_id=room.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            idempotency_key="old-room",
        )
    with subtests.test("who manages access is told, and nobody else"):
        html = assert_safe(admin.get(url(ready, "schedules")))
        assert "1 agenda foi criada antes" in html and "Vincular à agenda médica" in html
        reception = client_for(ready.a.reception)
        assert "Vincular à agenda médica" not in assert_safe(reception.get(url(ready, "schedules")))
        assert reception.post(url(ready, "schedules"), {"form": "claim"}).status_code == 404
    with subtests.test("marking once is enough"):
        response = admin.post(url(ready, "schedules"), {"form": "claim"}, follow=True)
        html = assert_safe(response)
        assert "1 calendário foi vinculado à agenda médica" in html and "Vincular à agenda médica" not in html
        response = admin.post(url(ready, "schedules"), {"form": "claim"}, follow=True)
        assert "já estavam vinculados" in assert_safe(response)


def test_the_schedules_page_lists_the_calendars_the_person_reads(ready, subtests):
    organization = ready.org_a.pk
    reception = client_for(ready.a.reception)
    ics = reverse("skeleton_calendar:calendar-ics", args=(organization, ready.schedule.calendar_id))
    with subtests.test("the schedules, with the ways out of the core calendar"):
        html = assert_safe(reception.get(url(ready, "schedules")))
        section = html[html.index('id="calendars-heading"') :]
        assert "Agendas de atendimento" in section and url(ready, "schedule", ready.schedule.sysid) in section
        assert ics in section and reverse("skeleton_calendar:home", args=(organization,)) in section
        assert url(ready, "calendar-subscribe", ready.schedule.calendar_id) in section
        assert reverse("skeleton_calendar:calendars", args=(organization,)) in section
        # The link is one per calendar: the personal feed, which joins every calendar, is not offered here.
        assert reverse("skeleton_calendar_me:feed-token") not in section and "só daquele calendário" in section
        assert "Vincular à agenda médica" not in html
        assert "valem só para as agendas de atendimento" in section
        assert "Outros calendários" not in section and "Maria" not in html
    with subtests.test("the other calendars apart, after the first visit to the core calendar"):
        assert reception.get(reverse("skeleton_calendar:home", args=(organization,))).status_code == 200
        section = assert_safe(reception.get(url(ready, "schedules")))
        section = section[section.index('id="calendars-heading"') :]
        assert "Outros calendários" in section and "Seu calendário" in section
    with subtests.test("the download is of that calendar, for who reads it"):
        response = reception.get(ics)
        assert response.status_code == 200 and response["Content-Type"].startswith("text/calendar")
        assert client_for(ready.a.finance).get(ics).status_code == 404
    with subtests.test("who reads no schedule sees no calendar of one"):
        html = assert_safe(client_for(ready.a.finance).get(url(ready, "schedules")))
        assert "Agenda da Dra. Ana" not in html and "Agendas de atendimento" not in html
    with subtests.test("organization B sees nothing of A"):
        html = assert_safe(client_for(ready.b.admin).get(url(ready, "schedules", organization=ready.org_b)))
        assert "Agenda da Dra. Ana" not in html and str(ready.schedule.calendar_id) not in html
