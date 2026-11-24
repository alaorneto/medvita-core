"""The reception pages of #134 and the way back to the booking page of #130, through the real views."""

import io
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from skeleton.service_api import Forbidden, NotFound
from skeleton.testing.jobs import run_pending_jobs

from ..extension import RETENTION_GUARDS, isolated_registries
from ..service_api import CoverageInput, PatientService
from .helpers import new_patient, setup_registry
from .test_views import assert_safe, client_for, url

CPF = "52998224725"
FORM = {"full_name": "Ana Retorno", "sex": "female", "contact_preference": "phone"}


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    with isolated_registries():
        yield clinic


def service():
    return PatientService()


def book_path(clinic, organization=None):
    return reverse("med_scheduling:book", args=((organization or clinic.org_a).pk,))


# ------------------------------------------------------------------------------- the form


def test_the_new_patient_page_has_four_groups_and_optional_masks(ready):
    html = assert_safe(client_for(ready.a.reception).get(url(ready, "create")))
    legends = re.findall(r'<fieldset class="patient-fieldset">\s*<legend>(.*?)</legend>', html)
    assert legends == ["Identificação", "Contato", "Endereço", "Observações"]
    assert 'data-mask="cpf"' in html and 'data-mask="phone"' in html and 'data-mask="cep"' in html
    assert re.search(r'<script src="[^"]*med_patients/med_patients\.js" defer>', html)
    assert 'http-equiv="refresh"' not in html


def test_without_the_script_the_server_normalizes_and_validates(ready):
    client = client_for(ready.a.reception)
    masked = {**FORM, "cpf": "529.982.247-25", "phone": "(81) 98888-7777", "postal_code": "50000-000"}
    assert client.post(url(ready, "create"), masked).status_code == 302
    with ready.as_user(ready.a.reception) as actor:
        (found,) = service().search(actor=actor, query=CPF).items
        info = service().get(actor=actor, patient_id=found.sysid)
    assert (info.cpf, info.phone, info.postal_code) == (CPF, "81988887777", "50000000")
    refused = client.post(url(ready, "create"), {**FORM, "full_name": "Outra", "cpf": "111.111.111-11"})
    assert refused.status_code == 400
    summary = re.search(r'<div class="error-summary".*?</div>', refused.content.decode(), re.S).group(0)
    assert "CPF" in summary and "111.111.111-11" not in summary and "11111111111" not in summary


def test_the_duplicates_warning_still_asks_and_still_lets_through(ready):
    new_patient(ready, full_name="Ana Retorno", cpf=CPF)
    client = client_for(ready.a.reception)
    asked = client.post(url(ready, "create"), {**FORM, "cpf": CPF})
    html = asked.content.decode()
    assert asked.status_code == 200 and "Possível paciente já cadastrado" in html
    assert 'name="confirm_duplicates"' in html and "cadastrar mesmo assim" in html
    # Same CPF is refused by the service even when confirmed: the form says so, without the value.
    same = client.post(url(ready, "create"), {**FORM, "cpf": CPF, "confirm_duplicates": "1"})
    assert same.status_code == 400 and "Já existe um paciente vivo com este CPF." in same.content.decode()
    homonym = client.post(url(ready, "create"), {**FORM, "confirm_duplicates": "1"})
    assert homonym.status_code == 302


# ------------------------------------------------------------------- back to the booking (#130)


def test_from_the_booking_page_the_new_patient_goes_back_there(ready):
    client = client_for(ready.a.reception)
    back = f"{book_path(ready)}?schedule=abc&day=2026-11-25&start=09%3A00"
    page = client.get(url(ready, "create"), {"next": back})
    html = assert_safe(page)
    assert f'name="next" value="{back.replace("&", "&amp;")}"' in html and "Voltar à marcação" in html
    # The duplicates step carries the way back too.
    new_patient(ready, full_name="Ana Retorno", birth_date=date(1990, 1, 2))
    homonym = {**FORM, "birth_date": "1990-01-02", "next": back}
    asked = client.post(url(ready, "create"), homonym)
    assert asked.status_code == 200 and "Possível paciente já cadastrado" in asked.content.decode()
    assert 'name="next"' in asked.content.decode()
    done = client.post(url(ready, "create"), {**homonym, "confirm_duplicates": "1"})
    assert done.status_code == 302
    target = urlsplit(done["Location"])
    assert target.path == book_path(ready)
    query = parse_qs(target.query)
    with ready.as_user(ready.a.reception) as actor:
        created = [item for item in service().search(actor=actor, query="ana retorno").items]
    assert len(created) == 2
    assert query["patient"][0] in {str(item.sysid) for item in created}
    assert (query["schedule"], query["day"], query["start"]) == (["abc"], ["2026-11-25"], ["09:00"])
    # Nothing personal in the way back: only the sysid.
    assert "Ana" not in done["Location"] and "Retorno" not in done["Location"]


@pytest.mark.parametrize(
    "back",
    (
        "https://evil.example/",
        "//evil.example/o/x/apps/med_scheduling/book/",
        "/o/{org}/apps/med_records/",
        "/o/{other}/apps/med_scheduling/book/",
        "/o/{org}/apps/med_scheduling/book/../../med_records/",
    ),
)
def test_any_other_way_back_is_ignored(ready, back):
    value = back.format(org=ready.org_a.pk, other=ready.org_b.pk)
    client = client_for(ready.a.reception)
    assert 'name="next"' not in client.get(url(ready, "create"), {"next": value}).content.decode()
    done = client.post(url(ready, "create"), {**FORM, "next": value})
    assert done.status_code == 302
    assert done["Location"].startswith(reverse("med_patients:list", args=(ready.org_a.pk,)))
    assert "evil" not in done["Location"] and "med_records" not in done["Location"]


# --------------------------------------------------------------------- detail and coverages


def test_the_status_change_waits_behind_a_disclosure(ready):
    patient = new_patient(ready)
    html = assert_safe(client_for(ready.a.reception).get(url(ready, "registration", patient.sysid)))
    disclosure = re.search(
        r'<details class="patient-disclosure[^"]*">\s*<summary>(.*?)</summary>(.*?)</details>', html, re.S
    )
    assert disclosure and disclosure.group(1) == "Alterar situação"
    assert reverse("med_patients:status", args=(ready.org_a.pk, patient.sysid)) in disclosure.group(2)
    assert " open" not in disclosure.group(0).split(">", 1)[0]
    reader = client_for(ready.a.finance).get(url(ready, "registration", patient.sysid)).content.decode()
    assert "Alterar situação" not in reader


def test_expired_and_expiring_coverages_are_marked(ready):
    patient = new_patient(ready)
    today = timezone.localdate()
    with ready.as_user(ready.a.reception) as actor:
        for name, days in (("Vencida", -1), ("Perto", 10), ("Longe", 200), ("Semdata", None)):
            until = today + timedelta(days=days) if days is not None else None
            service().add_coverage(
                actor=actor,
                patient_id=patient.sysid,
                data=CoverageInput(insurer_name=name, card_number=name[-4:], valid_until=until),
            )
    html = assert_safe(client_for(ready.a.reception).get(url(ready, "coverages", patient.sysid)))
    rows = {
        name: row
        for row in re.findall(r"<tr>.*?</tr>", html, re.S)
        for name in re.findall(r'<span class="cell-primary">(\w+)</span>', row)
    }
    assert "Vencido</span>" in rows["Vencida"] and "Vence em" not in rows["Vencida"]
    assert "Vence em 10 dias" in rows["Perto"] and "Vencido</span>" not in rows["Perto"]
    assert "Vence" not in rows["Longe"] and "Vence" not in rows["Semdata"]


# ---------------------------------------------------------------------------------- import


@pytest.fixture
def files(tmp_path):
    from django.conf import settings

    storage = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(tmp_path / "files"), "base_url": None},
    }
    with override_settings(STORAGES={**settings.STORAGES, "skeleton_files": storage}):
        yield


def test_import_shows_progress_and_the_real_count(ready, files):
    raw = "Nome;CPF\nAna Um;\nBeto Dois;\nCaio Três;11111111111\n".encode()
    with ready.as_user(ready.a.reception) as actor:
        batch = service().start_import(actor=actor, stream=io.BytesIO(raw), idempotency_key="page-import")
        batch = service().map_import(
            actor=actor,
            batch_id=batch.sysid,
            mapping=(("Nome", "full_name"), ("CPF", "cpf")),
            expected_revision=batch.revision,
        )
    client = client_for(ready.a.reception)
    page = url(ready, "import", batch.sysid)
    validating = assert_safe(client.get(page))
    assert "data-import-poll" in validating and f'href="{page}">Atualizar</a>' in validating
    assert 'http-equiv="refresh"' not in validating and "med_patients/med_patients.js" in validating
    run_pending_jobs()
    validated = assert_safe(client.get(page))
    assert "data-import-poll" not in validated and "Importar 2 pacientes" in validated
    with ready.as_user(ready.a.reception) as actor:
        checked = service().import_status(actor=actor, batch_id=batch.sysid)
        service().apply_import(actor=actor, batch_id=batch.sysid, expected_revision=checked.revision)
    importing = assert_safe(client.get(page))
    assert "data-import-poll" in importing and "<progress" in importing and "0 de 3 linhas processadas" in importing
    run_pending_jobs()
    completed = assert_safe(client.get(page))
    assert "data-import-poll" not in completed and "<progress" not in completed


# --------------------------------------------------------------------------------- privacy


def test_a_vetoed_anonymization_shows_the_reason_instead_of_the_form(ready):
    patient = new_patient(ready, cpf=CPF)
    admin = client_for(ready.a.admin)
    page = url(ready, "privacy", patient.sysid)
    assert 'name="confirm_code"' in admin.get(page).content.decode()
    RETENTION_GUARDS.add("med_patients.keep", lambda *, patient_id: "Prontuário dentro da guarda legal.", caller=None)
    html = assert_safe(admin.get(page))
    assert "data-anonymization-vetoed" in html and "Prontuário dentro da guarda legal." in html
    assert 'name="confirm_code"' not in html
    assert reverse("med_patients:anonymize", args=(ready.org_a.pk, patient.sysid)) not in html
    # The restriction is still offered, and the service still refuses a forged attempt.
    assert reverse("med_patients:restrict", args=(ready.org_a.pk, patient.sysid)) in html
    forged = admin.post(
        reverse("med_patients:anonymize", args=(ready.org_a.pk, patient.sysid)),
        {"revision": 1, "confirm_code": patient.code},
    )
    assert forged.status_code == 302
    with ready.as_user(ready.a.admin) as actor:
        assert service().get(actor=actor, patient_id=patient.sysid).anonymized_at is None


def test_a_failing_guard_vetoes_too(ready):
    patient = new_patient(ready)

    def broken(**kwargs):
        raise RuntimeError("down")

    RETENTION_GUARDS.add("med_patients.broken", broken, caller=None)
    with ready.as_user(ready.a.admin) as actor:
        (reason,) = service().anonymization_vetoes(actor=actor, patient_id=patient.sysid)
    assert "med_patients.broken" in reason
    assert (
        'name="confirm_code"'
        not in client_for(ready.a.admin).get(url(ready, "privacy", patient.sysid)).content.decode()
    )


def test_the_vetoes_are_for_who_manages_the_registry(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.admin) as actor:
        assert service().anonymization_vetoes(actor=actor, patient_id=patient.sysid) == ()
    with ready.as_user(ready.a.reception) as actor, pytest.raises(Forbidden):
        service().anonymization_vetoes(actor=actor, patient_id=patient.sysid)
    with ready.as_user(ready.b.admin, ready.b.organization) as actor, pytest.raises(NotFound):
        service().anonymization_vetoes(actor=actor, patient_id=patient.sysid)


# ----------------------------------------------------------------------- list and setup link


def test_the_clinic_setup_is_linked_for_who_can_open_it(ready):
    setup = reverse("med_patients:clinic_setup", args=(ready.org_a.pk,))
    admin_list = assert_safe(client_for(ready.a.admin).get(url(ready, "list")))
    assert f'href="{setup}"' in admin_list
    reception_list = assert_safe(client_for(ready.a.reception).get(url(ready, "list")))
    assert setup not in reception_list
    assert client_for(ready.a.reception).get(setup).status_code == 404
    steps = assert_safe(client_for(ready.a.admin).get(setup))
    assert '<ol class="setup-steps' in steps and '<span class="setup-step-number" aria-hidden="true">1</span>' in steps


def test_without_a_registry_only_an_administrator_gets_the_way_to_set_it_up(clinic):
    setup = reverse("med_patients:clinic_setup", args=(clinic.org_a.pk,))
    assert f'href="{setup}"' in client_for(clinic.a.admin).get(url(clinic, "list")).content.decode()
    # Before the registry exists the reception has nothing to read here (404), and no way to the setup.
    reception = client_for(clinic.a.reception).get(url(clinic, "list"))
    assert reception.status_code == 404 and setup not in reception.content.decode()


def test_the_list_keeps_cursor_pagination(ready, monkeypatch):
    from .. import views

    for index in range(3):
        new_patient(ready, full_name=f"Paginado {index}")
    client = client_for(ready.a.reception)
    monkeypatch.setattr(views, "PAGE_SIZE", 2)
    first = client.get(url(ready, "list"), {"q": "paginado"}).content.decode()
    following = re.search(r'href="(\?[^"]*cursor=[^"]+)"', first).group(1).replace("&amp;", "&")
    second = client.get(url(ready, "list") + following).content.decode()
    assert "Paginado 0" in first and "Paginado 1" in first and "Paginado 2" not in first
    assert "Paginado 2" in second and "q=paginado" in following
