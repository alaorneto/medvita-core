"""REST API of the scheduling app: authorization by the schedule, revision in If-Match, notes only in the detail."""

import json

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
    for field in ("organization", "code", "status", "is_fit_in", "billing_code"):
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
