"""Pages of the patients app: the whole reception flow, authorization by the registry, safe HTML."""

import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from ..extension import PATIENT_SECTIONS, PatientSection, isolated_registries
from ..service_api import PatientService
from .helpers import new_patient, setup_registry

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
UNSAFE = re.compile(r"\sstyle=|\son[a-z]+=", re.IGNORECASE)
APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    return clinic


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(clinic, name, *args, organization=None):
    return reverse(f"med_patients:{name}", args=((organization or clinic.org_a).pk, *args))


def assert_safe(response):
    html = response.content.decode()
    assert not INLINE_SCRIPT.search(html), "inline script"
    assert not UNSAFE.search(html), "style= or on*= attribute"
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert title.strip().endswith("Skeleton") or "·" in title
    return html


def test_pages_use_only_the_service():
    source = (APP_DIR / "views.py").read_text(encoding="utf-8")
    assert ".objects" not in source and "authorized_queryset" not in source and "from .services" not in source


def test_reception_flow(ready):
    client = client_for(ready.a.reception)
    response = client.post(
        url(ready, "create"),
        {"full_name": "João Teste", "cpf": "529.982.247-25", "sex": "male", "contact_preference": "phone"},
    )
    assert response.status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (summary,) = PatientService().search(actor=actor, query="joao").items
    detail = url(ready, "detail", summary.sysid)
    html = assert_safe(client.get(detail))
    assert "João Teste" in html and "529.982.247-25" in html

    duplicate = client.post(
        url(ready, "create"),
        {"full_name": "João Teste", "cpf": "52998224725", "sex": "male", "contact_preference": "phone"},
    )
    assert duplicate.status_code == 200 and "Possível paciente já cadastrado" in duplicate.content.decode()

    edit = client.post(
        url(ready, "edit", summary.sysid),
        {
            "full_name": "João Teste",
            "cpf": "52998224725",
            "sex": "male",
            "contact_preference": "phone",
            "city": "Recife",
            "revision": 1,
        },
    )
    assert edit.status_code == 302
    stale = client.post(
        url(ready, "edit", summary.sysid),
        {"full_name": "João Teste", "sex": "male", "contact_preference": "phone", "city": "Olinda", "revision": 1},
    )
    assert stale.status_code == 400 and "mudou desde que a página abriu" in stale.content.decode()

    assert (
        client.post(url(ready, "guardians", summary.sysid), {"name": "Maria Mãe", "relationship": "mother"}).status_code
        == 302
    )
    assert "Maria Mãe" in assert_safe(client.get(url(ready, "guardians", summary.sysid)))
    assert (
        client.post(
            url(ready, "coverages", summary.sysid), {"insurer_name": "Plano Bom", "card_number": "999"}
        ).status_code
        == 302
    )
    assert "Plano Bom" in assert_safe(client.get(url(ready, "coverages", summary.sysid)))
    assert (
        client.post(
            url(ready, "consents", summary.sysid), {"purpose": "med_patients.contact", "collected_via": "paper"}
        ).status_code
        == 302
    )
    with ready.as_user(ready.a.reception) as actor:
        (consent,) = PatientService().consents(actor=actor, patient_id=summary.sysid)
    revoke = client.post(url(ready, "consent-revoke", summary.sysid, consent.sysid), {"revision": consent.revision})
    assert revoke.status_code == 302
    for page in ("list", "create"):
        assert_safe(client.get(url(ready, page)))
    for page in ("consents", "timeline", "edit"):
        assert_safe(client.get(url(ready, page, summary.sysid)))


def test_without_a_grant_the_patient_is_404_and_the_list_empty(ready):
    patient = new_patient(ready)
    outsider = client_for(ready.b.reception)
    assert outsider.get(url(ready, "detail", patient.sysid)).status_code == 404
    finance = client_for(ready.a.finance)
    assert finance.get(url(ready, "detail", patient.sysid)).status_code == 200
    assert finance.get(url(ready, "edit", patient.sysid)).status_code == 404
    html = finance.get(url(ready, "detail", patient.sysid)).content.decode()
    assert "Alterar cadastro" not in html
    foreign = new_patient(ready, ready.b, full_name="Outra Clínica Única")
    assert "Outra Clínica Única" not in client_for(ready.a.reception).get(url(ready, "list")).content.decode()
    assert client_for(ready.a.reception).get(url(ready, "detail", foreign.sysid)).status_code == 404


def test_section_of_an_app_follows_its_activation(ready):
    patient = new_patient(ready)
    client = client_for(ready.a.reception)
    with isolated_registries():
        PATIENT_SECTIONS.add(
            "med_scheduling.extra",
            PatientSection("med_scheduling.extra", "Aba Extra", "med_patients:timeline"),
            caller=None,
        )
        assert "Aba Extra" in client.get(url(ready, "detail", patient.sysid)).content.decode()
        with ready.app_disabled("med_scheduling"):
            assert "Aba Extra" not in client.get(url(ready, "detail", patient.sysid)).content.decode()


def test_setup_page_is_for_administrators(clinic):
    assert client_for(clinic.a.reception).get(url(clinic, "setup")).status_code == 404
    admin = client_for(clinic.a.admin)
    response = admin.post(
        url(clinic, "setup"), {"name": "Cadastro", "writer_groups": [str(clinic.a.groups["reception"])]}
    )
    assert response.status_code == 302
    assert client_for(clinic.a.reception).get(url(clinic, "list")).status_code == 200


def test_bad_filters_answer_400(ready):
    assert client_for(ready.a.reception).get(url(ready, "list") + "?status=lost").status_code == 400
