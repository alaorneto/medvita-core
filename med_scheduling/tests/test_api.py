"""REST API of the scheduling app: authorization by the schedule, revision in If-Match, notes only in the detail."""

import json
from datetime import datetime, timedelta

import pytest
from django.test import Client
from django.urls import reverse

from .booking import at, book, prepare


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def api(ready, name, *args, organization=None):
    return reverse(f"med_scheduling_api:{name}", args=((organization or ready.org_a).pk, *args))


def post(client, address, body=None, **headers):
    return client.post(address, data=json.dumps(body or {}), content_type="application/json", **headers)


def test_book_list_detail_and_transitions(ready):
    client = client_for(ready.a.reception)
    schedules = client.get(api(ready, "schedules")).json()["results"]
    assert [item["sysid"] for item in schedules] == [str(ready.schedule.sysid)]
    slots = client.get(
        api(ready, "slots", ready.schedule.sysid) + f"?start={ready.monday:%Y-%m-%d}&type={ready.kind.sysid}"
    ).json()["results"]
    assert at(ready, 9).isoformat() in {item["starts_at"] for item in slots} or len(slots) == 8

    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(ready.kind.sysid),
        "starts_at": at(ready, 9).isoformat(),
        "notes": "dor de cabeça",
    }
    assert post(client, api(ready, "appointments"), body).status_code == 400  # no Idempotency-Key
    created = post(client, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="api-1")
    assert created.status_code == 201, created.content
    appointment = created.json()
    assert "notes" not in appointment
    again = post(client, api(ready, "appointments"), body, HTTP_IDEMPOTENCY_KEY="api-1")
    assert again.json()["sysid"] == appointment["sysid"]

    listed = client.get(api(ready, "appointments") + f"?patient={ready.patient.sysid}").json()["results"]
    assert [item["sysid"] for item in listed] == [appointment["sysid"]]
    assert "dor de cabeça" not in json.dumps(listed)
    detail = client.get(api(ready, "appointment", appointment["sysid"]))
    assert detail.json()["notes"] == "dor de cabeça" and detail["ETag"] == f'"{appointment["revision"]}"'

    transition = api(ready, "transition", appointment["sysid"], "confirm")
    assert post(client, transition).status_code == 400  # no If-Match
    confirmed = post(client, transition, HTTP_IF_MATCH=f'"{appointment["revision"]}"')
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    stale = post(client, api(ready, "transition", appointment["sysid"], "check-in"), HTTP_IF_MATCH='"1"')
    assert stale.status_code == 409
    revision = confirmed.json()["revision"]
    moved = post(
        client,
        api(ready, "transition", appointment["sysid"], "reschedule"),
        {"starts_at": at(ready, 10).isoformat()},
        HTTP_IF_MATCH=f'"{revision}"',
    )
    assert moved.status_code == 200 and moved.json()["status"] == "scheduled"
    cancelled = post(
        client,
        api(ready, "transition", appointment["sysid"], "cancel"),
        {"reason": "patient"},
        HTTP_IF_MATCH=f'"{moved.json()["revision"]}"',
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    unknown = post(client, api(ready, "transition", appointment["sysid"], "delete"), HTTP_IF_MATCH='"1"')
    assert unknown.status_code == 404


def test_system_fields_are_refused(ready, subtests):
    client = client_for(ready.a.reception)
    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(ready.kind.sysid),
        "starts_at": at(ready, 9).isoformat(),
    }
    for field in ("organization", "code", "status", "is_fit_in", "billing_code", "arrival_number", "is_priority"):
        with subtests.test(field):
            response = post(client, api(ready, "appointments"), {**body, field: "x"}, HTTP_IDEMPOTENCY_KEY=field)
            assert response.status_code == 400


def test_authorization_and_isolation(ready, subtests):
    appointment = book(ready, 9)
    outsider = client_for(ready.b.reception)
    reception = client_for(ready.a.reception)
    monday = f"?start={ready.monday:%Y-%m-%d}"
    for name, args, query in (
        ("slots", (ready.schedule.sysid,), monday),
        ("appointment", (appointment.sysid,), ""),
    ):
        with subtests.test(route=name):
            assert reception.get(api(ready, name, *args) + query).status_code == 200
            assert outsider.get(api(ready, name, *args, organization=ready.org_b) + query).status_code == 404
            assert client_for(ready.a.finance).get(api(ready, name, *args) + query).status_code == 404
    for name in ("schedules", "appointments"):
        with subtests.test(route=name):
            assert outsider.get(api(ready, name, organization=ready.org_b)).json()["results"] == []
    outside_transition = post(
        outsider,
        api(ready, "transition", appointment.sysid, "confirm", organization=ready.org_b),
        HTTP_IF_MATCH=f'"{appointment.revision}"',
    )
    assert outside_transition.status_code == 404
    finance = client_for(ready.a.finance)
    assert finance.get(api(ready, "appointment", appointment.sysid)).status_code == 404
    assert finance.get(api(ready, "appointments")).json()["results"] == []
    denied = post(
        finance,
        api(ready, "transition", appointment.sysid, "confirm"),
        HTTP_IF_MATCH=f'"{appointment.revision}"',
    )
    assert denied.status_code == 404
    with ready.app_disabled("med_scheduling"):
        for name, args in (("schedules", ()), ("appointments", ()), ("appointment", (appointment.sysid,))):
            assert reception.get(api(ready, name, *args)).status_code in (403, 404, 503)


def test_the_payment_comes_from_the_kind_unless_the_request_says(ready, subtests):
    from ..service_api import SchedulingService

    with ready.as_user(ready.a.admin) as admin:
        insured = SchedulingService().add_appointment_type(
            actor=admin, code="unimed", name="Unimed", payment_kind="insurance", idempotency_key="unimed"
        )
    client = client_for(ready.a.reception)
    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(insured.sysid),
    }

    def create(hour, key, **extra):
        return post(
            client,
            api(ready, "appointments"),
            {**body, "starts_at": at(ready, hour).isoformat(), **extra},
            HTTP_IDEMPOTENCY_KEY=key,
        )

    with subtests.test("inherited"):
        created = create(9, "inherited")
        assert created.status_code == 201 and created.json()["payment_kind"] == "insurance"
    with subtests.test("explicit"):
        created = create(10, "explicit", payment_kind="courtesy")
        assert created.status_code == 201 and created.json()["payment_kind"] == "courtesy"
    with subtests.test("unknown"):
        assert create(11, "unknown", payment_kind="voucher").status_code == 400


def walk_in_monday(ready, capacity=2):
    """Mondays: walk-in from 08:00 to 12:00 with ``capacity`` places, booked time from 14:00 to 18:00."""
    from datetime import date

    from ..service_api import AvailabilityRuleInput, SchedulingService

    with ready.as_user(ready.a.reception) as actor:
        current = SchedulingService().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
        SchedulingService().set_availability(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            rules=(
                AvailabilityRuleInput(0, 480, 720, date(2026, 1, 1), mode="walk_in", capacity=capacity),
                AvailabilityRuleInput(0, 840, 1080, date(2026, 1, 1)),
            ),
            expected_revision=current,
        )


def test_walk_in_through_the_api(ready, subtests):
    from ..service_api import ScheduleTypeInput, SchedulingService
    from .helpers import new_patient

    walk_in_monday(ready)
    client = client_for(ready.a.reception)
    monday = ready.monday.isoformat()
    plan = api(ready, "plan", ready.schedule.sysid) + f"?start={monday}"
    queue = api(ready, "queue", ready.schedule.sysid) + f"?date={monday}"
    body = {
        "schedule": str(ready.schedule.sysid),
        "patient": str(ready.patient.sysid),
        "appointment_type": str(ready.kind.sysid),
    }

    def create(hour, key, **extra):
        return post(
            client,
            api(ready, "appointments"),
            {**body, "starts_at": at(ready, hour).isoformat(), **extra},
            HTTP_IDEMPOTENCY_KEY=key,
        )

    with subtests.test("the plan says the mode and the room of each period"):
        periods = client.get(plan).json()["results"]
        assert [(item["start_minute"], item["mode"], item["capacity"], item["taken"]) for item in periods] == [
            (480, "walk_in", 2, 0),
            (840, "booked", None, 0),
        ]
        assert [item["is_exception"] for item in periods] == [False, False]
        both = client.get(plan + f"&end={(ready.monday + timedelta(days=7)).isoformat()}").json()["results"]
        assert len(both) == 4
        assert client.get(api(ready, "plan", ready.schedule.sysid)).status_code == 400
        assert client.get(plan + "&end=2020-01-01").status_code == 400
    with subtests.test("booked without an hour, in the session of the period"):
        created = create(9, "walk-1", mode="walk_in")
        assert created.status_code == 201, created.content
        first = created.json()
        assert (first["mode"], first["arrival_number"], first["duration_minutes"]) == ("walk_in", None, 30)
        assert datetime.fromisoformat(first["starts_at"]) == at(ready, 8)
        assert datetime.fromisoformat(first["ends_at"]) == at(ready, 12)
        assert "is_priority" not in first
    with subtests.test("the mode has to be the one of the period"):
        for hour, mode in ((9, "booked"), (15, "walk_in")):
            refused = create(hour, f"wrong-{hour}", mode=mode)
            assert (refused.status_code, refused.json()["code"]) == (409, "mode_mismatch"), refused.content
        assert create(9, "unknown", mode="queue").status_code == 400
        assert create(15, "default").json()["mode"] == "booked"
    with subtests.test("beyond the places of the period"):
        second = create(9, "walk-2", mode="walk_in", patient=str(new_patient(ready).sysid))
        assert second.status_code == 201
        full = create(9, "walk-3", mode="walk_in", patient=str(new_patient(ready).sysid))
        assert (full.status_code, full.json()["code"]) == (409, "session_full")
        assert client.get(plan).json()["results"][0]["is_full"] is True
    with subtests.test("a kind the schedule does not take by order of arrival"):
        with ready.as_user(ready.a.admin) as admin:
            other = SchedulingService().add_appointment_type(
                actor=admin, code="exame", name="Exame", idempotency_key="exame"
            )
        with ready.as_user(ready.a.reception) as actor:
            current = SchedulingService().schedule(actor=actor, schedule_id=ready.schedule.sysid).revision
            SchedulingService().set_schedule_types(
                actor=actor,
                schedule_id=ready.schedule.sysid,
                types=(ScheduleTypeInput(ready.kind.sysid), ScheduleTypeInput(other.sysid, None, True, False)),
                expected_revision=current,
            )
        refused = create(9, "kind", mode="walk_in", fit_in=True, appointment_type=str(other.sysid))
        assert (refused.status_code, refused.json()["code"]) == (409, "type_not_allowed")
    check_in = api(ready, "transition", first["sysid"], "check-in")
    with subtests.test("the arrival takes a number, and may carry the priority"):
        assert post(client, check_in, {"priority": "maybe"}, HTTP_IF_MATCH=f'"{first["revision"]}"').status_code == 400
        assert post(client, check_in, {"note": "x"}, HTTP_IF_MATCH=f'"{first["revision"]}"').status_code == 400
        arrived = post(client, check_in, {"priority": True}, HTTP_IF_MATCH=f'"{first["revision"]}"')
        assert arrived.status_code == 200, arrived.content
        first = arrived.json()
        assert (first["status"], first["arrival_number"]) == ("arrived", 1) and "is_priority" not in first
        later = post(
            client,
            api(ready, "transition", second.json()["sysid"], "check-in"),
            HTTP_IF_MATCH=f'"{second.json()["revision"]}"',
        )
        assert later.status_code == 200 and later.json()["arrival_number"] == 2
    with subtests.test("the queue and the detail carry the priority; the list does not"):
        (session,) = client.get(queue).json()["results"]
        assert (session["capacity"], session["taken"], session["is_full"]) == (2, 2, True)
        assert [(entry["appointment"]["sysid"], entry["is_priority"]) for entry in session["waiting"]] == [
            (first["sysid"], True),
            (second.json()["sysid"], False),
        ]
        assert session["expected"] == []
        assert client.get(api(ready, "appointment", first["sysid"])).json()["is_priority"] is True
        listed = client.get(api(ready, "appointments") + f"?schedule={ready.schedule.sysid}").json()
        assert len(listed["results"]) == 3 and "is_priority" not in json.dumps(listed)
        assert client.get(api(ready, "queue", ready.schedule.sysid)).status_code == 400
        assert client.get(api(ready, "queue", ready.schedule.sysid) + "?date=hoje").status_code == 400
    priority = api(ready, "priority", first["sysid"])
    with subtests.test("the priority is corrected with the revision"):
        assert post(client, priority, {"priority": False}).status_code == 400  # no If-Match
        assert post(client, priority, {"priority": False}, HTTP_IF_MATCH='"1"').status_code == 409
        assert post(client, priority, {}, HTTP_IF_MATCH=f'"{first["revision"]}"').status_code == 400
        assert post(client, priority, {"priority": "x"}, HTTP_IF_MATCH=f'"{first["revision"]}"').status_code == 400
        assert (
            post(
                client, priority, {"priority": False, "status": "x"}, HTTP_IF_MATCH=f'"{first["revision"]}"'
            ).status_code
            == 400
        )
        changed = post(client, priority, {"priority": False}, HTTP_IF_MATCH=f'"{first["revision"]}"')
        assert changed.status_code == 200 and "is_priority" not in changed.json()
        assert changed["ETag"] == f'"{changed.json()["revision"]}"'
        assert client.get(api(ready, "appointment", first["sysid"])).json()["is_priority"] is False
        (session,) = client.get(queue).json()["results"]
        assert [entry["is_priority"] for entry in session["waiting"]] == [False, False]
        assert client.get(priority).status_code == 405
    with subtests.test("who does not read the schedule, and organization B"):
        finance, outsider = client_for(ready.a.finance), client_for(ready.b.reception)
        for name, query in (("plan", f"?start={monday}"), ("queue", f"?date={monday}")):
            assert finance.get(api(ready, name, ready.schedule.sysid) + query).status_code == 404
            foreign = api(ready, name, ready.schedule.sysid, organization=ready.org_b) + query
            assert outsider.get(foreign).status_code == 404
        revision = changed.json()["revision"]
        assert post(finance, priority, {"priority": True}, HTTP_IF_MATCH=f'"{revision}"').status_code == 404
        away = api(ready, "priority", first["sysid"], organization=ready.org_b)
        assert post(outsider, away, {"priority": True}, HTTP_IF_MATCH=f'"{revision}"').status_code == 404
        assert client.get(api(ready, "appointment", first["sysid"])).json()["is_priority"] is False
