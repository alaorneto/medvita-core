"""The draft editor is one form: no typed text is lost, and signing seals exactly what was sent (#117)."""

import re
from collections import Counter

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from skeleton.service_api import NotFound

from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare, save, start

ICD_SAMPLE = "J45;Asma\nJ45.0;Asma predominantemente alérgica\n"


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def draft(ready):
    chart = open_chart(ready, new_patient(ready))
    encounter = start(ready, chart)
    save(ready, encounter, "med_records.free_text", text="queixa inicial")
    return encounter.header.sysid


def doctor_client(ready, user=None):
    client = Client()
    client.force_login(user or ready.a.doctor)
    return client


def edit_url(ready, encounter_id, name="encounter_edit"):
    return reverse(f"med_records:{name}", args=(ready.org_a.pk, encounter_id))


def info(ready, encounter_id):
    with ready.as_user(ready.a.doctor) as actor:
        return RecordsService().encounter(actor=actor, encounter_id=encounter_id)


def two_cards(ready, encounter_id, *, first_text, systolic, action):
    """The stored free text (card 0) and a new vitals card (card 1), as the editor posts them."""
    current = info(ready, encounter_id)
    (stored,) = current.sections
    return {
        "action": action,
        "revision": current.header.revision,
        "cards": 2,
        "s0-section": stored.sysid,
        "s0-text": first_text,
        "s1-type": "med_records.vitals",
        "s1-position": 0,
        "s1-systolic": systolic,
    }


def test_signing_seals_the_text_that_was_never_saved_on_its_own(ready, draft):
    client = doctor_client(ready)
    response = client.post(
        edit_url(ready, draft), two_cards(ready, draft, first_text="texto novo", systolic="130", action="sign")
    )
    assert response.status_code == 302 and response["Location"] == edit_url(ready, draft, "encounter_sign")
    signed = client.post(response["Location"], {"revision": info(ready, draft).header.revision})
    assert signed.status_code == 302
    sealed = info(ready, draft)
    assert sealed.header.signed
    texts = {section.section_type: section for section in sealed.sections}
    assert texts["med_records.free_text"].text == "texto novo"
    assert '"systolic":130' in texts["med_records.vitals"].data_json.replace(" ", "")


def test_an_invalid_field_keeps_everything_typed_and_saves_nothing(ready, draft):
    before = info(ready, draft).header.revision
    response = doctor_client(ready).post(
        edit_url(ready, draft), two_cards(ready, draft, first_text="não se perde", systolic="abc", action="sign")
    )
    assert response.status_code == 400
    html = response.content.decode()
    assert "não se perde" in html and 'value="abc"' in html
    assert "Nada foi salvo" in html and 'id="id_s1-systolic"' in html and "errorlist" in html
    after = info(ready, draft)
    assert after.header.revision == before and not after.header.signed
    assert [section.text for section in after.sections] == ["queixa inicial"]


@pytest.mark.parametrize("action", ["add", "search", "template", "save"])
def test_every_button_saves_what_was_typed(ready, draft, action):
    data = two_cards(ready, draft, first_text=f"digitado antes de {action}", systolic="", action=action)
    data.update({"add_type": "med_records.plan", "cid": "asma", "template_name": "Meu modelo"})
    response = doctor_client(ready).post(edit_url(ready, draft), data)
    assert response.status_code in (200, 302), response.status_code
    assert [section.text for section in info(ready, draft).sections] == [f"digitado antes de {action}"]


def test_the_editor_repeats_no_id(ready, draft):
    html = doctor_client(ready).get(edit_url(ready, draft) + "?add=med_records.vitals").content.decode()
    repeated = [name for name, count in Counter(re.findall(r'\bid="([^"]+)"', html)).items() if count > 1]
    assert repeated == []
    chart_tab = reverse("med_records:patient_section", args=(ready.org_a.pk, info(ready, draft).header.patient_id))
    page = doctor_client(ready).get(chart_tab).content.decode()
    assert [name for name, count in Counter(re.findall(r'\bid="([^"]+)"', page)).items() if count > 1] == []


def test_a_found_code_goes_into_the_diagnoses(ready, draft, tmp_path):
    sample = tmp_path / "cid10.csv"
    sample.write_text(ICD_SAMPLE, encoding="utf-8")
    call_command("load_icd10", str(sample), "--confirm")
    current = info(ready, draft)
    (stored,) = current.sections
    data = {
        "revision": current.header.revision,
        "cards": 2,
        "s0-section": stored.sysid,
        "s0-text": "queixa inicial",
        "s1-type": "med_records.assessment",
        "s1-position": 0,
        "s1-diagnoses": "",
        "cid": "asma",
    }
    client = doctor_client(ready)
    found = client.post(edit_url(ready, draft), {**data, "action": "search"})
    assert found.status_code == 200 and 'value="use_icd:J45.0"' in found.content.decode()
    data["revision"] = info(ready, draft).header.revision
    used = client.post(edit_url(ready, draft), {**data, "action": "use_icd:J45.0"})
    assert used.status_code == 200
    diagnoses = next(s for s in info(ready, draft).sections if s.section_type == "med_records.assessment")
    assert '"code":"J45.0"' in diagnoses.data_json.replace(" ", "")


def test_discarding_asks_first_and_only_the_author_discards(ready, draft):
    address = edit_url(ready, draft, "encounter_discard")
    client = doctor_client(ready)
    page = client.get(address)
    assert page.status_code == 200 and "Isso não se desfaz" in page.content.decode()
    assert doctor_client(ready, ready.a.reception).get(address).status_code == 404
    assert doctor_client(ready, ready.b.doctor).get(address).status_code == 404
    assert info(ready, draft).header.signed is False  # The GET changed nothing.
    response = client.post(address, {"revision": info(ready, draft).header.revision})
    assert response.status_code == 302
    with ready.as_user(ready.a.doctor) as actor, pytest.raises(NotFound):
        RecordsService().encounter(actor=actor, encounter_id=draft)


def test_a_stale_revision_signs_nothing(ready, draft):
    client = doctor_client(ready)
    stale = info(ready, draft).header.revision
    save(ready, info(ready, draft), "med_records.free_text", text="mudou em outra aba")
    response = client.post(edit_url(ready, draft, "encounter_sign"), {"revision": stale})
    assert response.status_code == 409 and "mudou desde que a página abriu" in response.content.decode()
    assert not info(ready, draft).header.signed
