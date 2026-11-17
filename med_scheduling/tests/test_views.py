"""Pages of the scheduling app: booking and attendance through the screens, authorization, safe HTML."""

import re
from datetime import datetime
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from applications.med_patients.service_api import PatientService

from ..service_api import SchedulingService
from .booking import at, book, prepare

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


def test_every_page_renders_safe_html(ready, subtests):
    appointment = book(ready, 9)
    client = client_for(ready.a.admin)
    pages = {
        "day": url(ready, "day") + f"?date={ready.monday:%Y-%m-%d}",
        "week": url(ready, "week", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}",
        "book": url(ready, "book") + f"?patient={ready.patient.sysid}",
        "appointment": url(ready, "appointment", appointment.sysid),
        "reception": url(ready, "reception"),
        "waitlist": url(ready, "waitlist"),
        "settings": url(ready, "settings"),
        "schedules": url(ready, "schedules"),
        "schedule": url(ready, "schedule", ready.schedule.sysid),
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

    current = detail(ready, row.sysid)
    response = client.post(
        url(ready, "cancel", row.sysid), {"reason": "patient", "note": "", "revision": current.revision}
    )
    assert response.status_code == 302
    assert detail(ready, row.sysid).status == "cancelled"


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
        with CaptureQueriesContext(connection) as context:
            assert client.get(address).status_code == 200
        return len(context)

    book(ready, 8)
    client.get(address)
    one = count()
    for hour, minute in ((8, 30), (9, 0), (9, 30), (10, 0), (10, 30), (11, 0)):
        book(ready, hour, minute)
    assert count() == one
