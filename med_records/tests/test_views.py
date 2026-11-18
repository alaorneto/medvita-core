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
    response = doctor.post(url(ready, "encounter_new", chart.sysid), {"kind": "consultation", "template": ""})
    assert response.status_code == 302
    encounter_id = response["Location"].rstrip("/").split("/")[-2]
    edit = url(ready, "encounter_edit", encounter_id)
    html = assert_safe(doctor.get(edit + "?add=med_records.vitals"))
    assert "Salvar seção" in html
    with ready.as_user(ready.a.doctor) as actor:
        revision = RecordsService().encounter(actor=actor, encounter_id=encounter_id).header.revision
    saved = doctor.post(
        edit,
        {
            "action": "section",
            "section_type": "med_records.vitals",
            "position": 0,
            "revision": revision,
            "s-systolic": "120",
            "s-weight": "70",
            "s-height": "175",
        },
    )
    assert saved.status_code == 302
    with ready.as_user(ready.a.doctor) as actor:
        revision = RecordsService().encounter(actor=actor, encounter_id=encounter_id).header.revision
    doctor.post(
        edit,
        {
            "action": "section",
            "section_type": "med_records.free_text",
            "position": 0,
            "revision": revision,
            "s-text": XSS,
        },
    )
    with ready.as_user(ready.a.doctor) as actor:
        revision = RecordsService().encounter(actor=actor, encounter_id=encounter_id).header.revision
    signed = doctor.post(edit, {"action": "sign", "revision": revision})
    assert signed.status_code == 302
    page = assert_safe(doctor.get(url(ready, "encounter", encounter_id)))
    assert "Registro assinado em" in page and "Sem assinatura digital ICP-Brasil" in page and "22.9" in page
    assert XSS not in page and "&lt;script&gt;" in page
    printed = assert_safe(doctor.get(url(ready, "encounter_print", encounter_id)))
    assert XSS not in printed
    addendum = doctor.post(url(ready, "addendum", encounter_id), {"text": "correção", "idempotency_key": "ad"})
    assert addendum.status_code == 302 and "/edit/" in addendum["Location"]

    created = doctor.post(url(ready, "document_new", chart.sysid), {"kind": "med_records.certificate", "template": ""})
    document_id = created["Location"].rstrip("/").split("/")[-2]
    with ready.as_user(ready.a.doctor) as actor:
        revision = RecordsService().document(actor=actor, document_id=document_id).header.revision
    issued = doctor.post(
        url(ready, "document_edit", document_id),
        {"title": "Atestado", "body": "Repouso de 2 dias.", "revision": revision, "action": "issue"},
    )
    assert issued.status_code == 302
    assert "Repouso de 2 dias." in assert_safe(doctor.get(url(ready, "document_print", document_id)))
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
    response = doctor.get(url(ready, "attend", appointment.sysid))
    assert response.status_code == 302 and "/edit/" in response["Location"]
    again = doctor.get(url(ready, "attend", appointment.sysid))
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
