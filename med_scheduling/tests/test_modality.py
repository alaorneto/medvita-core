"""In person or telehealth: the kind says it, the appointment keeps its copy and publishes it."""

import pytest
from django.test import Client
from django.urls import reverse

from skeleton.service_api import Conflict, InvalidInput
from skeleton.testing.events import capture_events

from ..service_api import SchedulingService
from .booking import at, prepare
from .helpers import as_admin


@pytest.fixture
def ready(clinic):
    prepared = prepare(clinic)
    with as_admin(clinic) as admin:
        prepared.tele = SchedulingService().add_appointment_type(
            actor=admin, code="tele", name="Teleconsulta", modality="telehealth", idempotency_key="tele"
        )
    return prepared


def _book(ready, hour, kind, key, **extra):
    with ready.as_user(ready.a.reception) as actor:
        return SchedulingService().book(
            actor=actor,
            schedule_id=ready.schedule.sysid,
            patient_id=ready.patient.sysid,
            appointment_type_id=kind.sysid,
            starts_at=at(ready, hour),
            idempotency_key=key,
            **extra,
        )


def test_the_appointment_takes_the_modality_of_the_kind_and_publishes_it(ready):
    assert ready.kind.modality == "in_person" and ready.tele.modality == "telehealth"
    with capture_events() as events:
        tele = _book(ready, 9, ready.tele, "tele")
        office = _book(ready, 10, ready.kind, "office")
        chosen = _book(ready, 11, ready.kind, "chosen", modality="telehealth")
    assert (tele.modality, office.modality, chosen.modality) == ("telehealth", "in_person", "telehealth")
    assert [dict(event.data)["modality"] for event in events] == ["telehealth", "in_person", "telehealth"]
    with pytest.raises(InvalidInput) as error:
        _book(ready, 11, ready.kind, "unknown", modality="video")
    assert "modality" in error.value.errors


def test_the_modality_changes_until_the_appointment_starts(ready):
    service = SchedulingService()
    booked = _book(ready, 9, ready.kind, "office")
    with ready.as_user(ready.a.reception) as actor:
        with capture_events() as events:
            changed = service.set_modality(
                actor=actor, appointment_id=booked.sysid, modality="telehealth", expected_revision=booked.revision
            )
            same = service.set_modality(
                actor=actor, appointment_id=booked.sysid, modality="telehealth", expected_revision=changed.revision
            )
        assert changed.modality == "telehealth" and same.revision == changed.revision
        assert [(event.event_type, dict(event.data)["modality"]) for event in events] == [
            ("med_scheduling.appointment_modality_changed", "telehealth")
        ]
        with pytest.raises(Conflict) as stale:
            service.set_modality(
                actor=actor, appointment_id=booked.sysid, modality="in_person", expected_revision=booked.revision
            )
        assert stale.value.code == "stale_revision"
        arrived = service.check_in(actor=actor, appointment_id=booked.sysid, expected_revision=changed.revision)
    with ready.as_user(ready.a.doctor) as doctor:
        started = service.start(actor=doctor, appointment_id=booked.sysid, expected_revision=arrived.revision)
    with ready.as_user(ready.a.reception) as actor, pytest.raises(Conflict) as late:
        service.set_modality(
            actor=actor, appointment_id=booked.sysid, modality="in_person", expected_revision=started.revision
        )
    assert late.value.code == "invalid_transition"


def test_lists_filter_by_modality(ready):
    service = SchedulingService()
    tele = _book(ready, 9, ready.tele, "tele")
    _book(ready, 10, ready.kind, "office")
    with ready.as_user(ready.a.reception) as actor:
        found = service.appointments(actor=actor, schedule_id=ready.schedule.sysid, modality="telehealth").items
        everything = service.appointments(actor=actor, schedule_id=ready.schedule.sysid).items
        with pytest.raises(InvalidInput):
            service.appointments(actor=actor, modality="video")
    assert [row.sysid for row in found] == [tele.sysid] and len(everything) == 2


def test_the_kind_changes_and_the_page_switches_the_modality(ready):
    service = SchedulingService()
    with as_admin(ready) as admin:
        changed = service.update_appointment_type(
            actor=admin,
            type_id=ready.kind.sysid,
            changes=(("modality", "telehealth"),),
            expected_revision=ready.kind.revision,
        )
        with pytest.raises(InvalidInput):
            service.update_appointment_type(
                actor=admin, type_id=ready.kind.sysid, changes=(("modality", "x"),), expected_revision=changed.revision
            )
    assert changed.modality == "telehealth"
    booked = _book(ready, 9, ready.kind, "office")
    assert booked.modality == "telehealth"
    client = Client()
    client.force_login(ready.a.reception)
    org = ready.org_a.pk
    page = client.get(reverse("med_scheduling:appointment", args=(org, booked.sysid))).content.decode()
    assert "Teleconsulta" in page and reverse("med_scheduling:modality", args=(org, booked.sysid)) in page
    response = client.post(
        reverse("med_scheduling:modality", args=(org, booked.sysid)),
        {"modality": "in_person", "revision": booked.revision},
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        assert service.appointment(actor=actor, appointment_id=booked.sysid).appointment.modality == "in_person"
    with as_admin(ready) as admin:
        service.set_schedule_access(
            actor=admin,
            schedule_id=ready.schedule.sysid,
            writer_group_ids=(ready.a.groups["reception"],),
            reader_group_ids=(ready.a.groups["finance"],),
            writer_user_ids=(),
            expected_revision=service.schedule(actor=admin, schedule_id=ready.schedule.sysid).revision,
        )
    reader = Client()
    reader.force_login(ready.a.finance)
    page = reader.get(reverse("med_scheduling:appointment", args=(org, booked.sysid))).content.decode()
    assert "Presencial" in page and reverse("med_scheduling:modality", args=(org, booked.sysid)) not in page
    refused = reader.post(
        reverse("med_scheduling:modality", args=(org, booked.sysid)), {"modality": "telehealth", "revision": 9}
    )
    assert refused.status_code == 404
