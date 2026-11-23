"""Items another app offers, consumed in an encounter: photographed, sealed and published without health data."""

import pytest
from django.db import transaction

from skeleton.service_api import Conflict, InvalidInput, NotFound
from skeleton.testing.events import capture_events

from ..extension import isolated_registries
from ..models import EncounterConsumption
from ..service_api import ConsumableItem, ConsumptionInput, RecordsService, register_consumable_provider
from .helpers import new_patient, open_chart, prepare, save, start

PAYLOAD = {"encounter", "provider", "item_ref", "quantity", "lot"}


def _offer(*, actor):
    return (ConsumableItem("gauze", "Gaze estéril", "un"), ConsumableItem("vac-01", "Vacina antirrábica", "dose"))


@pytest.fixture
def ready(clinic):
    prepared = prepare(clinic)
    with isolated_registries():
        register_consumable_provider("med_records.test_stock", _offer)
        yield prepared


@pytest.fixture
def draft(ready):
    chart = open_chart(ready, new_patient(ready))
    return save(ready, start(ready, chart), "med_records.free_text", text="Curativo")


def _add(ready, info, ref, quantity=1, lot="", user=None):
    with ready.as_user(user or ready.a.doctor) as actor:
        return RecordsService().add_consumption(
            actor=actor,
            encounter_id=info.header.sysid,
            item=ConsumptionInput("med_records.test_stock", ref, quantity, lot),
            expected_revision=info.header.revision,
        )


def test_the_signature_seals_the_items_and_publishes_only_the_reference(ready, draft):
    service = RecordsService()
    with ready.as_user(ready.a.doctor) as actor:
        offered = service.consumable_items(actor=actor, encounter_id=draft.header.sysid)
    assert [(item.provider, item.ref, item.label, item.unit) for item in offered] == [
        ("med_records.test_stock", "gauze", "Gaze estéril", "un"),
        ("med_records.test_stock", "vac-01", "Vacina antirrábica", "dose"),
    ]
    info = _add(ready, draft, "gauze", "2,5")
    info = _add(ready, info, "vac-01", 1, "L123")
    assert [(item.item_label, item.quantity, item.unit, item.lot) for item in info.consumption] == [
        ("Gaze estéril", "2.5", "un", ""),
        ("Vacina antirrábica", "1", "dose", "L123"),
    ]
    with ready.as_user(ready.a.doctor) as actor, capture_events() as events:
        signed = service.sign_encounter(
            actor=actor, encounter_id=info.header.sysid, expected_revision=info.header.revision
        )
        assert service.verify_encounter(actor=actor, encounter_id=signed.header.sysid).valid
        assert service.consumable_items(actor=actor, encounter_id=signed.header.sysid) == ()
    consumed = [dict(event.data) for event in events if event.event_type == "med_records.items_consumed"]
    assert all(set(payload) == PAYLOAD for payload in consumed)
    assert [(item["item_ref"], item["quantity"], item["lot"]) for item in consumed] == [
        ("gauze", "2.5", ""),
        ("vac-01", "1", "L123"),
    ]
    assert {item["encounter"] for item in consumed} == {str(signed.header.sysid)}
    assert "antirrábica" not in repr([event.data for event in events]) and len(signed.consumption) == 2
    with pytest.raises(Conflict) as late:
        _add(ready, signed, "gauze")
    assert late.value.code == "signed"
    with ready.as_user(ready.a.doctor):
        row = EncounterConsumption.objects.filter(encounter_id=signed.header.sysid).first()
        row.quantity = 3
        with pytest.raises(Exception, match="(?i)seal"), transaction.atomic():
            row.save()


def test_items_are_validated_and_removed_while_a_draft(ready, draft):
    for quantity in (0, -1, "1.2345", "abc", 1.5, True, 100000):
        with pytest.raises(InvalidInput) as error:
            _add(ready, draft, "gauze", quantity)
        assert "quantity" in error.value.errors, quantity
    with pytest.raises(InvalidInput) as error:
        _add(ready, draft, "unknown")
    assert "item_ref" in error.value.errors
    with pytest.raises(InvalidInput):
        _add(ready, draft, "gauze", 1, "L" * 41)
    info = _add(ready, draft, "gauze")
    with ready.as_user(ready.a.doctor) as actor:
        info = RecordsService().remove_consumption(
            actor=actor,
            encounter_id=info.header.sysid,
            consumption_id=info.consumption[0].sysid,
            expected_revision=info.header.revision,
        )
    assert info.consumption == ()
    with pytest.raises(NotFound), ready.as_user(ready.b.doctor, ready.org_b) as outsider:
        RecordsService().consumable_items(actor=outsider, encounter_id=draft.header.sysid)


def test_without_a_provider_nothing_is_offered(ready, draft):
    with isolated_registries(empty=True), ready.as_user(ready.a.doctor) as actor:
        assert RecordsService().consumable_items(actor=actor, encounter_id=draft.header.sysid) == ()
        with pytest.raises(InvalidInput):
            RecordsService().add_consumption(
                actor=actor,
                encounter_id=draft.header.sysid,
                item=ConsumptionInput("med_records.test_stock", "gauze"),
                expected_revision=draft.header.revision,
            )


def test_the_editor_shows_the_section_only_with_a_provider(ready, draft):
    from django.test import Client
    from django.urls import reverse

    client = Client()
    client.force_login(ready.a.doctor)
    address = reverse("med_records:encounter_edit", args=(ready.org_a.pk, draft.header.sysid))
    with isolated_registries(empty=True):
        assert "Itens consumidos" not in client.get(address).content.decode()
    assert "Itens consumidos" in client.get(address).content.decode()
    response = client.post(
        address,
        {
            "action": "consumption_add",
            "item": "med_records.test_stock|gauze",
            "quantity": "2",
            "lot": "",
            "revision": draft.header.revision,
        },
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.doctor) as actor:
        info = RecordsService().encounter(actor=actor, encounter_id=draft.header.sysid)
    assert [item.item_ref for item in info.consumption] == ["gauze"]
    with isolated_registries(empty=True):
        page = client.get(address).content.decode()
    assert "Gaze estéril" in page  # What was recorded stays listed, without the form to add more.
    assert 'value="consumption_add"' not in page
