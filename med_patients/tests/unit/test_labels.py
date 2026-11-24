"""The display filters of the patients app (no database): labels, tones of states and identifiers (#121, #122)."""

from types import SimpleNamespace

import pytest
from django.template import Context, Template

from ...models import Consent, ImportBatch, Patient
from ...templatetags.med_patients_labels import (
    CHOICES,
    IMPORT_REASONS,
    MARKER_TONE_CODE,
    STATE_TONE_CODE,
    TONES,
    patient_address,
    patient_contacts,
    patient_cpf,
    patient_import_failure,
    patient_import_reason,
    patient_label,
    patient_marker,
    patient_phone,
    patient_purpose,
    patient_section_title,
    patient_state,
)


def render(source: str, **context: object) -> str:
    return Template("{% load skeleton_format med_patients_labels %}" + source).render(Context(context))


@pytest.mark.parametrize("tone", sorted(STATE_TONE_CODE))
def test_state_codes_have_the_tone_they_stand_for(tone):
    html = render("{{ code|status_badge:'x' }}", code=STATE_TONE_CODE[tone])
    assert html == f'<span class="badge badge-{tone} badge-dot">x</span>'


@pytest.mark.parametrize("tone", sorted(MARKER_TONE_CODE))
def test_marker_codes_have_the_tone_they_stand_for(tone):
    assert render("{{ code|marker:'x' }}", code=MARKER_TONE_CODE[tone]) == f'<span class="badge badge-{tone}">x</span>'


@pytest.mark.parametrize(
    ("kind", "choices"),
    [("status", Patient.Status), ("consent_status", Consent.Status), ("import_status", ImportBatch.Status)],
)
def test_every_state_has_a_tone_and_a_label(kind, choices):
    assert {code for (domain, code) in TONES if domain == kind} == set(choices.values)
    assert CHOICES[kind] is choices
    for code, label in choices.choices:
        assert patient_label(code, kind) == str(label)


def test_states_and_markers():
    assert patient_state("active", "status") == "completed"
    assert patient_state("deceased", "status") == "withdrawn"
    assert patient_state("validated", "import_status") == "pending"
    assert patient_state("failed", "import_status") == "failed"
    assert patient_state("unknown", "status") == "withdrawn"  # Unknown is neutral.
    assert patient_marker("brand") == "primary" and patient_marker("other") == "private"
    html = render('{{ "importing"|patient_state:"import_status"|status_badge:"Importando" }}')
    assert html == '<span class="badge badge-brand badge-dot">Importando</span>'


def test_import_reasons_never_show_a_bare_code():
    assert patient_import_reason("duplicate_cpf") == str(IMPORT_REASONS["duplicate_cpf"])
    assert patient_import_reason("invalid_cpf") == "CPF inválido"
    unknown = patient_import_reason("invalid_<x>")
    assert unknown.startswith('Linha recusada<span class="cell-secondary">') and "invalid_&lt;x&gt;" in unknown
    assert patient_import_failure("forbidden").startswith("Quem enviou")
    assert 'translate="no">boom</code>' in patient_import_failure("boom")


def test_purpose_and_section_titles():
    assert (
        patient_purpose("med_patients.contact", {"med_patients.contact": "Contato por mensagem"})
        == "Contato por mensagem"
    )
    assert "Finalidade não disponível" in patient_purpose("gone.purpose", {})
    assert patient_section_title("med_patients") == "Pacientes"
    assert patient_section_title("no_such_app") == "no_such_app"


def test_identifiers_and_contacts():
    assert patient_cpf("52998224725") == "529.982.247-25"
    assert patient_cpf("123") == "123" and patient_cpf("") == "" and patient_cpf(None) == ""
    assert patient_phone("11988887777") == "(11) 98888-7777"
    assert patient_phone("1133334444") == "(11) 3333-4444"
    assert patient_phone("+5511988887777") == "+55 (11) 98888-7777"
    assert patient_phone("+12025550123") == "+12025550123" and patient_phone("") == ""
    person = SimpleNamespace(phone="11988887777", phone_secondary="", email="ana@example.com")
    assert patient_contacts(person) == "(11) 98888-7777 · ana@example.com"
    assert patient_contacts(SimpleNamespace(phone="", phone_secondary="", email="")) == "—"


def test_address_on_one_line():
    full = SimpleNamespace(
        street="Rua A",
        number="12",
        complement="apto 3",
        district="Centro",
        city="Campinas",
        state="SP",
        postal_code="13010000",
    )
    assert patient_address(full) == "Rua A, 12, apto 3 · Centro · Campinas/SP · CEP 13010-000"
    partial = SimpleNamespace(
        street="", number="", complement="", district="", city="Campinas", state="", postal_code=""
    )
    assert patient_address(partial) == "Campinas"
    empty = SimpleNamespace(street="", number="", complement="", district="", city="", state="", postal_code="")
    assert patient_address(empty) == "—"
