"""The clinical strip (#137): who the patient is and what they are allergic to, on the four screens where the doctor
decides, and nowhere for who does not read the chart."""

import re
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare

NAME = "Maria Faixa Clínica"
STRIP = re.compile(r"<section class=\"clinical-strip[^\"]*\"[^>]*data-clinical-strip>(.*?)</section>", re.S)


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def chart(ready):
    patient = new_patient(ready, full_name=NAME, birth_date=date(1980, 1, 15), sex="female")
    return open_chart(ready, patient)


def drafts(ready, chart):
    with ready.as_user(ready.a.doctor) as actor:
        encounter = RecordsService().start_encounter(actor=actor, chart_id=chart.sysid, idempotency_key="e")
        document = RecordsService().draft_document(
            actor=actor, chart_id=chart.sysid, kind="med_records.certificate", idempotency_key="d"
        )
    return encounter.header.sysid, document.header.sysid


def pages(ready, chart):
    encounter, document = drafts(ready, chart)
    org = ready.org_a.pk
    return {
        "encounter_edit": reverse("med_records:encounter_edit", args=(org, encounter)),
        "encounter": reverse("med_records:encounter", args=(org, encounter)),
        "document_edit": reverse("med_records:document_edit", args=(org, document)),
        "lists": reverse("med_records:lists", args=(org, chart.sysid)),
    }


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def strip_of(response):
    assert response.status_code == 200, response.status_code
    html = response.content.decode()
    found = STRIP.findall(html)
    assert len(found) == 1, "one strip per page"
    return html, found[0]


def test_the_strip_is_on_the_four_screens_with_name_age_sex_and_allergies(ready, chart, subtests):
    with ready.as_user(ready.a.doctor) as actor:
        RecordsService().add_allergy(
            actor=actor, chart_id=chart.sysid, substance="Penicilina", severity="severe", idempotency_key="a1"
        )
        RecordsService().add_allergy(
            actor=actor, chart_id=chart.sysid, substance="Látex", severity="moderate", idempotency_key="a2"
        )
        resolved = RecordsService().add_allergy(
            actor=actor, chart_id=chart.sysid, substance="Amendoim", severity="mild", idempotency_key="a3"
        )
        RecordsService().update_allergy(
            actor=actor,
            allergy_id=resolved.sysid,
            changes=(("status", "resolved"),),
            expected_revision=resolved.revision,
        )
    doctor = client_for(ready.a.doctor)
    for name, address in pages(ready, chart).items():
        with subtests.test(name):
            html, strip = strip_of(doctor.get(address))
            assert NAME in strip and "anos" in strip and "Feminino" in strip
            assert "clinical-strip-alert" in html  # The danger tokens of the app CSS.
            # Severe is written, not only painted: "GRAVE" next to the substance, the others by their severity.
            assert re.search(r'<li class="clinical-strip-severe">Penicilina · <strong>GRAVE</strong></li>', strip)
            assert "Látex · moderada" in strip
            assert "Amendoim" not in strip  # A resolved allergy leaves the strip.
            assert strip.index("Penicilina") < strip.index("Látex")
            # Read once: one labelled region, no live region, and the name is not the page heading too.
            assert re.search(r'<section class="clinical-strip[^"]*" aria-labelledby="clinical-strip-title"', html)
            assert "aria-live" not in strip and 'role="alert"' not in strip and 'role="status"' not in strip
            assert f"<h1>{NAME}</h1>" not in html


def test_without_allergies_the_strip_says_so(ready, chart, subtests):
    doctor = client_for(ready.a.doctor)
    for name, address in pages(ready, chart).items():
        with subtests.test(name):
            html, strip = strip_of(doctor.get(address))
            assert "Sem alergias registradas" in strip and NAME in strip
            assert "clinical-strip-alert" not in html


def test_who_does_not_read_the_chart_reaches_none_of_the_screens(ready, chart, subtests):
    addresses = pages(ready, chart)
    for role in ("reception", "finance"):
        client = client_for(getattr(ready.a, role))
        for name, address in addresses.items():
            with subtests.test(role=role, page=name):
                assert client.get(address).status_code == 404
    outsider = client_for(ready.b.doctor)
    for name, address in addresses.items():
        with subtests.test(role="doctor of B", page=name):
            foreign = address.replace(str(ready.org_a.pk), str(ready.org_b.pk))
            assert outsider.get(foreign).status_code == 404
