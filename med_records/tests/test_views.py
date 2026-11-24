"""Pages of the records app: the clinical flow, who sees what, escaping, no-store and titles."""

import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from applications.med_patients.service_api import PatientService

from ..service_api import RecordsService
from .helpers import book_arrived, new_patient, open_chart, prepare, register_doctor

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
UNSAFE = re.compile(r"\sstyle=|\son[a-z]+=", re.IGNORECASE)
APP_DIR = Path(__file__).resolve().parents[1]
NAME = "Maria Prontuario Secreta"
XSS = "<script>alert(1)</script>"


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def patient(ready):
    return new_patient(ready, full_name=NAME)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def url(ready, name, *args, organization=None):
    return reverse(f"med_records:{name}", args=((organization or ready.org_a).pk, *args))


def current_revision(ready, encounter_id):
    with ready.as_user(ready.a.doctor) as actor:
        return RecordsService().encounter(actor=actor, encounter_id=encounter_id).header.revision


def sections_of(ready, encounter_id):
    with ready.as_user(ready.a.doctor) as actor:
        return RecordsService().encounter(actor=actor, encounter_id=encounter_id).sections


def assert_safe(response, *, clinical=True):
    assert response.status_code == 200, response.status_code
    html = response.content.decode()
    assert not INLINE_SCRIPT.search(html), "inline script"
    assert not UNSAFE.search(html), "style= or on*= attribute"
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert "·" in title and NAME not in title
    if clinical:
        assert "no-store" in response.get("Cache-Control", "")
    return html


def test_pages_use_only_the_services():
    source = (APP_DIR / "views.py").read_text(encoding="utf-8")
    assert ".objects" not in source and "authorized_queryset" not in source and "from .services" not in source


def test_clinical_flow_through_the_pages(ready, patient):
    doctor = client_for(ready.a.doctor)
    section = url(ready, "patient_section", patient.sysid)
    assert "Abrir prontuário" in assert_safe(doctor.get(section))
    assert doctor.post(url(ready, "chart_open", patient.sysid)).status_code == 302
    with ready.as_user(ready.a.doctor) as actor:
        (chart,) = RecordsService().charts_for_patient(actor=actor, patient_id=patient.sysid)
    response = doctor.post(
        url(ready, "encounter_new", chart.sysid), {"encounter-kind": "consultation", "encounter-template": ""}
    )
    assert response.status_code == 302
    encounter_id = response["Location"].rstrip("/").split("/")[-2]
    edit = url(ready, "encounter_edit", encounter_id)
    html = assert_safe(doctor.get(edit + "?add=med_records.vitals"))
    assert "Revisar e assinar" in html
    revision = current_revision(ready, encounter_id)
    saved = doctor.post(
        edit,
        {
            "action": "save",
            "revision": revision,
            "cards": 1,
            "s0-type": "med_records.vitals",
            "s0-position": 0,
            "s0-systolic": "120",
            "s0-weight": "70",
            "s0-height": "175",
        },
    )
    assert saved.status_code == 302
    (vitals,) = sections_of(ready, encounter_id)
    # The free text card is new and never saved on its own: "Revisar e assinar" saves it first.
    to_sign = doctor.post(
        edit,
        {
            "action": "sign",
            "revision": current_revision(ready, encounter_id),
            "cards": 2,
            "s0-section": vitals.sysid,
            "s0-systolic": "120",
            "s0-weight": "70",
            "s0-height": "175",
            "s1-type": "med_records.free_text",
            "s1-position": 0,
            "s1-text": XSS,
        },
    )
    assert to_sign.status_code == 302 and to_sign["Location"] == url(ready, "encounter_sign", encounter_id)
    confirmation = assert_safe(doctor.get(to_sign["Location"]))
    assert "Sinais vitais" in confirmation and "Texto livre" in confirmation and "btn-danger" in confirmation
    signed = doctor.post(to_sign["Location"], {"revision": current_revision(ready, encounter_id)})
    assert signed.status_code == 302
    page = assert_safe(doctor.get(url(ready, "encounter", encounter_id)))
    assert "Registro assinado em" in page and "Sem assinatura digital ICP-Brasil" in page and "22.9" in page
    assert XSS not in page and "&lt;script&gt;" in page
    printed = assert_safe(doctor.get(url(ready, "encounter_print", encounter_id)))
    assert XSS not in printed
    addendum = doctor.post(url(ready, "addendum", encounter_id), {"text": "correção", "idempotency_key": "ad"})
    assert addendum.status_code == 302 and "/edit/" in addendum["Location"]

    created = doctor.post(
        url(ready, "document_new", chart.sysid), {"document-kind": "med_records.certificate", "document-template": ""}
    )
    document_id = created["Location"].rstrip("/").split("/")[-2]
    with ready.as_user(ready.a.doctor) as actor:
        revision = RecordsService().document(actor=actor, document_id=document_id).header.revision
    to_issue = doctor.post(
        url(ready, "document_edit", document_id),
        {"title": "Atestado", "body": "Repouso de 2 dias.", "revision": revision, "action": "issue"},
    )
    # #119: "Revisar e emitir" saves the draft and asks; the document is issued only on the confirmation.
    assert to_issue.status_code == 302 and to_issue["Location"] == url(ready, "document_issue", document_id)
    asked = assert_safe(doctor.get(to_issue["Location"]))
    assert "Emitir o documento" in asked and "Atestado" in asked
    with ready.as_user(ready.a.doctor) as actor:
        current = RecordsService().document(actor=actor, document_id=document_id).header
    assert not current.issued
    issued = doctor.post(to_issue["Location"], {"revision": current.revision})
    assert issued.status_code == 302
    printed = assert_safe(doctor.get(url(ready, "document_print", document_id)))
    assert "Repouso de 2 dias." in printed
    # #118: the signature line and the integrity footer are part of the printed document.
    assert "Assinatura e carimbo" in printed and "Código de verificação" in printed and "<footer" in printed
    listing = assert_safe(doctor.get(section))
    assert "Atestado" in listing and "Assinado" in listing
    assert assert_safe(doctor.get(url(ready, "lists", chart.sysid)))


def test_reception_sees_no_clinical_page(ready, patient):
    chart = open_chart(ready, patient)
    with ready.as_user(ready.a.doctor) as actor:
        draft = RecordsService().start_encounter(actor=actor, chart_id=chart.sysid, idempotency_key="x")
    reception = client_for(ready.a.reception)
    for address in (
        url(ready, "patient_section", patient.sysid),
        url(ready, "encounter", draft.header.sysid),
        url(ready, "encounter_edit", draft.header.sysid),
        url(ready, "lists", chart.sysid),
        url(ready, "access_log", chart.sysid),
        url(ready, "templates"),
    ):
        assert reception.get(address).status_code == 404, address
    patient_page = reception.get(reverse("med_patients:detail", args=(ready.org_a.pk, patient.sysid)))
    assert url(ready, "patient_section", patient.sysid) not in patient_page.content.decode()
    outsider = client_for(ready.b.doctor)
    assert outsider.get(url(ready, "encounter", draft.header.sysid, organization=ready.org_b)).status_code == 404


def test_attend_from_the_appointment(ready, patient):
    from applications.med_scheduling.service_api import SchedulingService

    appointment = book_arrived(ready, patient, register_doctor(ready))
    doctor = client_for(ready.a.doctor)
    page = doctor.get(reverse("med_scheduling:appointment", args=(ready.org_a.pk, appointment.sysid)))
    assert url(ready, "attend", appointment.sysid) in page.content.decode()
    response = doctor.post(url(ready, "attend", appointment.sysid))
    assert response.status_code == 302 and "/edit/" in response["Location"]
    again = doctor.post(url(ready, "attend", appointment.sysid))
    assert again["Location"] == response["Location"]
    with ready.as_user(ready.a.reception) as actor:
        current = SchedulingService().appointment(actor=actor, appointment_id=appointment.sysid).appointment
    assert current.status == "in_progress"
    with ready.as_user(ready.a.doctor) as actor:
        assert PatientService().summary(actor=actor, patient_id=patient.sysid).display_name == NAME


def test_setup_page(clinic):
    from .helpers import setup_patients, setup_practice

    setup_patients(clinic)
    setup_practice(clinic)
    admin = client_for(clinic.a.admin)
    assert_safe(admin.get(reverse("med_records:setup", args=(clinic.org_a.pk,))), clinical=False)
    response = admin.post(
        reverse("med_records:setup", args=(clinic.org_a.pk,)),
        {"mode": "shared", "name": "", "member_groups": [str(clinic.a.groups["professionals"])]},
    )
    assert response.status_code == 302
    assert client_for(clinic.a.reception).get(reverse("med_records:setup", args=(clinic.org_a.pk,))).status_code == 404


def test_clinical_list_endings_and_replacements_ask_first(ready, patient):
    from .helpers import start

    chart = open_chart(ready, patient)
    with ready.as_user(ready.a.doctor) as actor:
        allergy = RecordsService().add_allergy(
            actor=actor,
            chart_id=chart.sysid,
            substance="Dipirona",
            category="drug",
            severity="severe",
            reaction="",
            noted_on=None,
            idempotency_key="allergy",
        )
    doctor = client_for(ready.a.doctor)
    end = url(ready, "list_end", chart.sysid, "allergy", allergy.sysid)
    assert end in assert_safe(doctor.get(url(ready, "lists", chart.sysid)))
    asked = assert_safe(doctor.get(end))
    assert "Dipirona" in asked and "Marcar a alergia como resolvida" in asked
    assert client_for(ready.a.reception).get(end).status_code == 404
    assert doctor.get(url(ready, "list_end", chart.sysid, "other", allergy.sysid)).status_code == 404
    assert doctor.post(end, {"revision": allergy.revision}).status_code == 302
    with ready.as_user(ready.a.doctor) as actor:
        (stored,) = RecordsService().allergies(actor=actor, chart_id=chart.sysid)
    assert stored.status == "resolved"
    assert doctor.get(end).status_code == 404  # Nothing active left to resolve.
    draft = start(ready, chart, key="to-remove")
    with ready.as_user(ready.a.doctor) as actor:
        saved = RecordsService().save_section(
            actor=actor,
            encounter_id=draft.header.sysid,
            section_type="med_records.plan",
            text="x",
            expected_revision=draft.header.revision,
        )
    (section,) = saved.sections
    remove = url(ready, "section_remove", draft.header.sysid, section.sysid)
    assert "Remover a seção" in assert_safe(doctor.get(remove))
    assert client_for(ready.b.doctor).get(remove).status_code == 404
    assert doctor.post(remove, {"revision": saved.header.revision}).status_code == 302
    with ready.as_user(ready.a.doctor) as actor:
        assert RecordsService().encounter(actor=actor, encounter_id=draft.header.sysid).sections == ()
