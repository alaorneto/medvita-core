"""The scheduling API with the access token of a native client (#61): the same answers as the session."""

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext

from .booking import at, book, prepare


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def session(user):
    client = Client()
    client.force_login(user)
    return client


def api(ready, name, *args, organization=None):
    return reverse(f"med_scheduling_api:{name}", args=((organization or ready.org_a).pk, *args))


def post(client, address, body=None, **headers):
    return client.post(address, data=json.dumps(body or {}), content_type="application/json", **headers)


def narrowed(native_clients, user, client_id, scopes):
    native_clients.register(client_id, scopes=scopes)
    return native_clients.client(user, scope="openid " + " ".join(scopes), client_id=client_id)


def assert_scope_refused(response):
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == gettext("O token não tem o escopo exigido.")


def test_token_books_and_moves_like_the_session(ready, native_clients):
    token = native_clients.client(ready.a.reception)
    browser = session(ready.a.reception)
    assert token.get(api(ready, "schedules")).json() == browser.get(api(ready, "schedules")).json()
    slots = api(ready, "slots", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}&type={ready.kind.sysid}"
    assert token.get(slots).json() == browser.get(slots).json()
    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(ready.kind.sysid),
        "starts_at": at(ready, 9).isoformat(),
        "notes": "dor de cabeça",
    }
    assert post(token, api(ready, "appointments"), body).status_code == 400  # No Idempotency-Key.
    created = post(token, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="tok-1")
    assert created.status_code == 201, created.content
    appointment = created.json()
    assert post(token, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="tok-1").json() == appointment
    listed = api(ready, "appointments") + f"?patient={ready.patient.sysid}"
    assert token.get(listed).json() == browser.get(listed).json()
    detail = api(ready, "appointment", appointment["sysid"])
    by_token = token.get(detail)
    assert by_token.json() == browser.get(detail).json() and by_token.json()["notes"] == "dor de cabeça"
    assert by_token["ETag"] == f'"{appointment["revision"]}"'
    transition = api(ready, "transition", appointment["sysid"], "confirm")
    assert post(token, transition).status_code == 400  # No If-Match.
    confirmed = post(token, transition, HTTP_IF_MATCH=f'"{appointment["revision"]}"')
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert (
        post(token, api(ready, "transition", appointment["sysid"], "check-in"), HTTP_IF_MATCH='"1"').status_code == 409
    )
    cancelled = post(
        token,
        api(ready, "transition", appointment["sysid"], "cancel"),
        {"reason": "patient"},
        HTTP_IF_MATCH=f'"{confirmed.json()["revision"]}"',
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_methods_outside_token_methods_are_refused(ready, native_clients):
    appointment = book(ready, 9)
    token = native_clients.client(ready.a.reception)
    for method, url in (
        ("post", api(ready, "schedules")),
        ("patch", api(ready, "appointment", appointment.sysid)),
        ("delete", api(ready, "appointment", appointment.sysid)),
        ("get", api(ready, "transition", appointment.sysid, "confirm")),
        ("post", api(ready, "plan", ready.schedule.sysid)),
        ("post", api(ready, "queue", ready.schedule.sysid)),
        ("get", api(ready, "priority", appointment.sysid)),
    ):
        response = getattr(token, method)(url)
        assert response.status_code == 403 and response.json()["code"] == "token_not_allowed", (method, url)


def test_scope_and_role_and_organization(ready, native_clients):
    appointment = book(ready, 9)
    reader = narrowed(
        native_clients,
        ready.a.reception,
        "medvita-agenda",
        ("scheduling:read", "med_scheduling.practice:read", "med_scheduling.schedule:read"),
    )
    assert reader.get(api(ready, "schedules")).status_code == 200
    assert reader.get(api(ready, "appointment", appointment.sysid)).status_code == 200
    assert_scope_refused(
        post(reader, api(ready, "transition", appointment.sysid, "confirm"), HTTP_IF_MATCH=f'"{appointment.revision}"')
    )
    plan = api(ready, "plan", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}"
    queue = api(ready, "queue", ready.schedule.sysid) + f"?date={ready.monday:%Y-%m-%d}"
    assert reader.get(plan).status_code == reader.get(queue).status_code == 200
    assert_scope_refused(
        post(
            reader,
            api(ready, "priority", appointment.sysid),
            {"priority": True},
            HTTP_IF_MATCH=f'"{appointment.revision}"',
        )
    )
    patients_only = narrowed(native_clients, ready.a.reception, "medvita-patients", ("patients:read",))
    assert_scope_refused(patients_only.get(api(ready, "schedules")))
    assert_scope_refused(patients_only.get(plan))
    assert_scope_refused(patients_only.get(queue))
    foreign = native_clients.client(ready.b.reception)
    for name, address in (("plan", plan), ("queue", queue)):
        away = address.replace(str(ready.org_a.pk), str(ready.org_b.pk))
        assert foreign.get(away).status_code == 404, name
    # Finance does not run the front desk: the broad token carries scheduling:write and still cannot confirm.
    transition = api(ready, "transition", appointment.sysid, "confirm")
    by_token = post(native_clients.client(ready.a.finance), transition, HTTP_IF_MATCH=f'"{appointment.revision}"')
    by_session = post(session(ready.a.finance), transition, HTTP_IF_MATCH=f'"{appointment.revision}"')
    assert by_token.status_code == by_session.status_code and by_token.status_code in (403, 404)
    outsider = native_clients.client(ready.b.reception)
    assert outsider.get(api(ready, "appointment", appointment.sysid)).status_code == 404


def test_token_reads_the_plan_and_runs_the_queue_like_the_session(ready, native_clients):
    from .test_api import walk_in_monday

    walk_in_monday(ready)
    token = native_clients.client(ready.a.reception)
    browser = session(ready.a.reception)
    plan = api(ready, "plan", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}"
    queue = api(ready, "queue", ready.schedule.sysid) + f"?date={ready.monday:%Y-%m-%d}"
    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(ready.kind.sysid),
        "starts_at": at(ready, 9).isoformat(),
        "mode": "walk_in",
    }
    created = post(token, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="tok-walk")
    assert created.status_code == 201, created.content
    appointment = created.json()
    assert appointment["mode"] == "walk_in"
    assert post(browser, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="tok-walk").json() == appointment
    assert token.get(plan).json() == browser.get(plan).json()
    assert token.get(plan).json()["results"][0]["taken"] == 1
    arrived = post(
        token,
        api(ready, "transition", appointment["sysid"], "check-in"),
        {"priority": True},
        HTTP_IF_MATCH=f'"{appointment["revision"]}"',
    )
    assert arrived.status_code == 200 and arrived.json()["arrival_number"] == 1
    by_token = token.get(queue).json()
    assert by_token == browser.get(queue).json()
    assert by_token["results"][0]["waiting"][0]["is_priority"] is True
    priority = api(ready, "priority", appointment["sysid"])
    assert post(token, priority, {"priority": False}).status_code == 400  # No If-Match.
    assert post(token, priority, {"priority": False}, HTTP_IF_MATCH='"1"').status_code == 409
    changed = post(token, priority, {"priority": False}, HTTP_IF_MATCH=f'"{arrived.json()["revision"]}"')
    assert changed.status_code == 200 and "is_priority" not in changed.json()
    assert token.get(queue).json()["results"][0]["waiting"][0]["is_priority"] is False
