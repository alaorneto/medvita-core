"""The entry of the records and a readable history (#133), and "Atender" by POST only (#131)."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from skeleton.service_api import InvalidInput, NotFound

from ..service_api import RecordsService
from .helpers import book_arrived, new_patient, open_chart, prepare, register_doctor, save, start

NAME = "Joana Entrada Sigilosa"


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def patient(ready):
    return new_patient(ready, full_name=NAME)


@pytest.fixture
def chart(ready, patient):
    return open_chart(ready, patient)


def client_for(user, **options):
    client = Client(**options)
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_records:{name}", args=((organization or ready.org_a).pk, *args))


def title_of(response):
    return re.search(r"<title>(.*?)</title>", response.content.decode(), re.S).group(1)


def document_draft(ready, chart, *, user=None, key="doc"):
    with ready.as_user(user or ready.a.doctor) as actor:
        return RecordsService().draft_document(
            actor=actor, chart_id=chart.sysid, kind="med_records.certificate", idempotency_key=key
        )


# ------------------------------------------------------------------ my_drafts (service)


def test_my_drafts_are_only_the_actors_own(ready, chart):
    mine = start(ready, chart, key="mine")
    my_document = document_draft(ready, chart)
    with ready.as_user(ready.a.admin) as admin:
        theirs = RecordsService().start_encounter(actor=admin, chart_id=chart.sysid, idempotency_key="theirs")
    document_draft(ready, chart, user=ready.a.admin, key="their-doc")
    signed = save(ready, start(ready, chart, key="signed"), "med_records.free_text", text="x")
    with ready.as_user(ready.a.doctor) as doctor:
        RecordsService().sign_encounter(
            actor=doctor, encounter_id=signed.header.sysid, expected_revision=signed.header.revision
        )
        drafts = RecordsService().my_drafts(actor=doctor)
        assert {(item.kind, item.sysid) for item in drafts} == {
            ("encounter", mine.header.sysid),
            ("document", my_document.header.sysid),
        }
        assert theirs.header.sysid not in {item.sysid for item in drafts}
        assert all(item.chart_id == chart.sysid and item.patient_id == chart.patient_id for item in drafts)
        (only,) = RecordsService().my_drafts(actor=doctor, limit=1)
        assert only.sysid in {mine.header.sysid, my_document.header.sysid}
        assert len(RecordsService().my_drafts(actor=doctor, chart_id=chart.sysid)) == 2
        with pytest.raises(InvalidInput):
            RecordsService().my_drafts(actor=doctor, limit=0)
        RecordsService().discard_draft(
            actor=doctor, encounter_id=mine.header.sysid, expected_revision=mine.header.revision
        )
        assert [item.kind for item in RecordsService().my_drafts(actor=doctor)] == ["document"]
    with ready.as_user(ready.a.admin) as admin:
        assert {item.sysid for item in RecordsService().my_drafts(actor=admin)} >= {theirs.header.sysid}
        assert my_document.header.sysid not in {item.sysid for item in RecordsService().my_drafts(actor=admin)}


def test_my_drafts_need_the_archive_and_stay_in_the_organization(ready, chart):
    start(ready, chart, key="mine")
    with ready.as_user(ready.a.reception) as reception:
        assert RecordsService().my_drafts(actor=reception) == ()
        with pytest.raises(NotFound):
            RecordsService().my_drafts(actor=reception, chart_id=chart.sysid)
    with ready.as_user(ready.b.doctor, ready.org_b) as outsider:
        assert RecordsService().my_drafts(actor=outsider) == ()
        with pytest.raises(NotFound):
            RecordsService().my_drafts(actor=outsider, chart_id=chart.sysid)


# ------------------------------------------------------------------ the entry page


def test_entry_searches_by_post_and_lists_own_drafts(ready, patient, chart):
    mine = start(ready, chart, key="mine")
    with ready.as_user(ready.a.admin) as admin:
        theirs = RecordsService().start_encounter(actor=admin, chart_id=chart.sysid, idempotency_key="theirs")
    doctor = client_for(ready.a.doctor)
    page = doctor.get(url(ready, "home"))
    assert page.status_code == 200 and "no-store" in page.get("Cache-Control", "")
    html = page.content.decode()
    assert 'method="post"' in html and 'name="q"' in html and "Meus rascunhos" in html
    assert url(ready, "encounter_edit", mine.header.sysid) in html and mine.header.code in html
    assert url(ready, "encounter_edit", theirs.header.sysid) not in html and theirs.header.code not in html
    assert NAME in html  # The patient of the draft, by PatientService.
    found = doctor.post(url(ready, "home"), {"q": "Joana Sigilosa"})
    assert found.status_code == 200 and NAME not in title_of(found)
    assert url(ready, "patient_section", patient.sysid) in found.content.decode()
    missing = doctor.post(url(ready, "home"), {"q": "Ninguem Assim"})
    assert "Nenhum paciente encontrado." in missing.content.decode()
    # The form never puts the term in the address: the search answers only to POST.
    assert NAME not in doctor.get(url(ready, "home") + "?q=Joana").content.decode().split("Meus rascunhos")[0]


def test_entry_needs_csrf_for_the_search(ready, patient, chart):
    strict = client_for(ready.a.doctor, enforce_csrf_checks=True)
    assert strict.post(url(ready, "home"), {"q": "Joana"}).status_code == 403


def test_who_reads_no_archive_sees_no_entry(ready, patient, chart):
    start(ready, chart, key="mine")
    reception = client_for(ready.a.reception)
    page = reception.post(url(ready, "home"), {"q": "Joana"})
    html = page.content.decode()
    assert page.status_code == 200 and "Nenhum arquivo clínico que você possa ler." in html
    assert 'name="q"' not in html and "Meus rascunhos" not in html and NAME not in html
    outsider = client_for(ready.b.doctor)
    other = outsider.post(url(ready, "home", organization=ready.org_b), {"q": "Joana"})
    assert other.status_code == 200 and NAME not in other.content.decode()
    assert url(ready, "patient_section", chart.patient_id, organization=ready.org_b) not in other.content.decode()


# ------------------------------------------------------------------ the chart tab


def test_history_shows_type_reason_and_pages(ready, patient, chart):
    first = save(
        ready, start(ready, chart, key="e-0"), "med_records.anamnesis", (("chief_complaint", "Dor de cabeça " * 20),)
    )
    second = save(ready, start(ready, chart, key="e-1", kind="return"), "med_records.vitals", (("systolic", 120),))
    for number in range(2, 51):
        start(ready, chart, key=f"e-{number}")
    doctor = client_for(ready.a.doctor)
    section = url(ready, "patient_section", patient.sysid)
    page = doctor.get(section)
    html = page.content.decode()
    assert page.status_code == 200 and "Tipo e motivo" in html and "Retomar rascunho" in html
    prefix = url(ready, "encounter", first.header.sysid).rsplit(str(first.header.sysid), 1)[0]
    assert len(re.findall(rf'class="cell-primary" href="{re.escape(prefix)}[0-9a-f-]{{36}}/"', html)) == 50
    assert 'rel="next"' in html and "cursor=" in html
    assert first.header.code not in html  # The oldest is on the second page.
    next_url = re.search(r'href="(\?[^"]*cursor=[^"]*)"', html).group(1).replace("&amp;", "&")
    older = doctor.get(section + next_url)
    older_html = older.content.decode()
    assert older.status_code == 200 and first.header.code in older_html and 'rel="next"' not in older_html
    assert "Consulta" in older_html and "Dor de cabeça" in older_html and "…" in older_html
    assert ("Dor de cabeça " * 20).strip() not in older_html  # Cut to a line.
    assert second.header.code in html or second.header.code in older_html
    assert "Sinais vitais" in html + older_html and "Retorno" in html + older_html
    assert NAME not in title_of(older)
    assert doctor.get(section + "?cursor=not-a-cursor").status_code == 404
    with ready.as_user(ready.a.admin) as admin:
        actions = {entry.action for entry in RecordsService().access_log(actor=admin, chart_id=chart.sysid).items}
    assert "view_chart" in actions


def test_resume_is_only_for_the_actors_draft(ready, patient, chart):
    section = url(ready, "patient_section", patient.sysid)
    with ready.as_user(ready.a.admin) as admin:
        theirs = RecordsService().start_encounter(actor=admin, chart_id=chart.sysid, idempotency_key="theirs")
    doctor = client_for(ready.a.doctor)
    assert "Retomar rascunho" not in doctor.get(section).content.decode()
    mine = start(ready, chart, key="mine")
    html = doctor.get(section).content.decode()
    assert "Retomar rascunho" in html and url(ready, "encounter_edit", mine.header.sysid) in html
    assert url(ready, "encounter_edit", theirs.header.sysid) not in html


def test_seal_shows_a_short_code_and_the_whole_one_on_paper(ready, chart):
    draft = save(ready, start(ready, chart, key="seal"), "med_records.free_text", text="x")
    with ready.as_user(ready.a.doctor) as doctor:
        signed = RecordsService().sign_encounter(
            actor=doctor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
        )
    digest = signed.header.seal_digest
    client = client_for(ready.a.doctor)
    html = client.get(url(ready, "encounter", signed.header.sysid)).content.decode()
    assert "Código de verificação" in html and "Resumo SHA-256" not in html
    assert f'<span class="seal-digest-short" aria-hidden="true">{digest[:12]}…</span>' in html
    assert f'title="{digest}"' in html and f'<span class="seal-digest-full">{digest}</span>' in html
    printed = client.get(url(ready, "encounter_print", signed.header.sysid)).content.decode()
    assert f'<span class="seal-digest" translate="no">{digest}</span>' in printed and "seal-digest-short" not in printed


def test_access_log_names_people_and_hides_the_uuid(ready, chart):
    from ..models import AccessLog

    draft = save(ready, start(ready, chart, key="read"), "med_records.free_text", text="x")
    with ready.as_user(ready.a.doctor) as doctor:
        RecordsService().encounter(actor=doctor, encounter_id=draft.header.sysid)
    stranger = ready.b.doctor  # A person who is not a member of organization A.
    with ready.as_user(ready.a.admin):
        row = AccessLog.objects.filter(chart_id=chart.sysid).first()
        AccessLog(
            organization_id=row.organization_id,
            chart_id=chart.sysid,
            actor_id=stranger.pk,
            action="view_chart",
            origin="web",
            at=row.at,
        ).save()
    html = client_for(ready.a.admin).get(url(ready, "access_log", chart.sysid)).content.decode()
    assert "Pessoa indisponível" in html
    assert f">{stranger.pk}<" not in html  # Never the whole identifier as text.
    assert html.count("Pessoa indisponível") == 1  # The doctor, a member, is shown by name.


# ------------------------------------------------------------------ "Atender" (#131)


def test_attend_by_get_answers_405_and_creates_nothing(ready, patient):
    from applications.med_scheduling.service_api import SchedulingService

    appointment = book_arrived(ready, patient, register_doctor(ready))
    doctor = client_for(ready.a.doctor)
    assert doctor.get(url(ready, "attend", appointment.sysid)).status_code == 405
    with ready.as_user(ready.a.doctor) as actor:
        assert RecordsService().charts_for_patient(actor=actor, patient_id=patient.sysid) == ()
        assert RecordsService().my_drafts(actor=actor) == ()
    with ready.as_user(ready.a.reception) as actor:
        current = SchedulingService().appointment(actor=actor, appointment_id=appointment.sysid).appointment
    assert current.status == "arrived"
    strict = client_for(ready.a.doctor, enforce_csrf_checks=True)
    assert strict.post(url(ready, "attend", appointment.sysid)).status_code == 403
