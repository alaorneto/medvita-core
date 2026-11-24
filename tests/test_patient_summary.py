"""The patient opens on "Resumo" (#136): the panels each app registers, by role, organization and activation,
and the one patient header of the four apps."""

import re
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from applications.med_finance.service_api import ChargeItemInput, FinanceService
from applications.med_patients.service_api import CoverageInput, PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import SchedulingService
from skeleton.service_api import NotFound

from .journey import monday_at, new_patient, set_up

ALLERGY = "Dipirona Sódica"
MEDICATION = "Losartana Potássica"


class Ready:
    """The clinic fixture plus what the test prepared, forwarding everything else."""

    def __init__(self, clinic, **prepared):
        self._clinic = clinic
        self.__dict__.update(prepared)

    def __getattr__(self, name):
        return getattr(self._clinic, name)


# The decorative icons before a label (#144) are left out of markup comparisons.
ICON = re.compile(r"<svg\b[^>]*>.*?</svg>", re.S)


def without_icons(html):
    return ICON.sub("", html)


@pytest.fixture
def ready(clinic):
    a = set_up(clinic, clinic.a)
    set_up(clinic, clinic.b)
    born = timezone.localdate().replace(year=timezone.localdate().year - 10, day=1)
    patient = new_patient(clinic, clinic.a, full_name="Paciente do Resumo", birth_date=born, sex="female")
    with clinic.as_user(clinic.a.reception) as actor:
        appointment = SchedulingService().book(
            actor=actor,
            schedule_id=a.schedule.sysid,
            patient_id=patient.sysid,
            appointment_type_id=a.kind.sysid,
            starts_at=monday_at(9),
            idempotency_key="book",
        )
        FinanceService().create_charge(
            actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="charge"
        )
        PatientService().add_coverage(
            actor=actor,
            patient_id=patient.sysid,
            data=CoverageInput(
                insurer_name="Plano Resumo",
                card_number="4321",
                is_primary=True,
                valid_until=timezone.localdate() + timedelta(days=10),
            ),
        )
    with clinic.as_user(clinic.a.doctor) as doctor:
        chart = RecordsService().open_chart(actor=doctor, patient_id=patient.sysid)
        RecordsService().add_allergy(
            actor=doctor, chart_id=chart.sysid, substance=ALLERGY, severity="severe", idempotency_key="allergy"
        )
        RecordsService().add_medication(actor=doctor, chart_id=chart.sysid, name=MEDICATION, idempotency_key="med")
    return Ready(clinic, patient=patient, appointment=appointment, chart=chart)


def page(user, address):
    client = Client()
    client.force_login(user)
    return client.get(address)


def summary_url(clinic, organization=None):
    return reverse("med_patients:detail", args=((organization or clinic.org_a).pk, clinic.patient.sysid))


def panels(html):
    return re.findall(r'data-panel="([a-z_.]+)"', html)


def panel_codes(clinic, user, organization=None):
    with clinic.as_user(user, organization) as actor:
        return [row.code for row in PatientService().summary_panels(actor=actor, patient_id=clinic.patient.sysid)]


def test_the_patient_opens_on_the_summary_with_the_panels_of_each_role(ready, subtests):
    with subtests.test("reception: appointments, balance and coverage; no allergies"):
        response = page(ready.a.reception, summary_url(ready))
        html = without_icons(response.content.decode())
        assert response.status_code == 200
        current = re.search(r'<a href="([^"]+)" aria-current="page">([^<]+)</a>', html)
        assert current.group(2) == "Resumo" and current.group(1) == summary_url(ready)
        assert panels(html) == ["med_scheduling.appointments", "med_finance.balance", "med_patients.coverage"]
        assert ready.appointment.code not in html  # The panel links the appointment by its date, not its code.
        assert reverse("med_scheduling:appointment", args=(ready.org_a.pk, ready.appointment.sysid)) in html
        assert "Marcar consulta" in html and "Nova conta" in html
        assert "R$" in html and "Plano Resumo" in html and "Vence em 10 dias" in html
        assert ALLERGY not in html and MEDICATION not in html and "Alergias" not in html
    with subtests.test("doctor: appointments, allergies and coverage; no balance"):
        html = without_icons(page(ready.a.doctor, summary_url(ready)).content.decode())
        assert panels(html) == ["med_scheduling.appointments", "med_records.allergies", "med_patients.coverage"]
        assert ALLERGY in html and "Alergia grave" in html and MEDICATION in html
        assert "Nova conta" not in html and "Saldo em aberto" not in html
    with subtests.test("finance: balance and coverage; no schedule, no chart"):
        assert panel_codes(ready, ready.a.finance) == ["med_finance.balance", "med_patients.coverage"]
    with subtests.test("admin reads everything"):
        assert panel_codes(ready, ready.a.admin) == [
            "med_scheduling.appointments",
            "med_records.allergies",
            "med_finance.balance",
            "med_patients.coverage",
        ]


def test_organization_b_sees_nothing_of_a(ready, subtests):
    for role in ("reception", "doctor", "finance", "admin"):
        user = getattr(ready.b, role)
        with subtests.test(role=role):
            assert page(user, summary_url(ready, ready.org_b)).status_code == 404
            with ready.as_user(user, ready.org_b) as actor, pytest.raises(NotFound):
                PatientService().summary_panels(actor=actor, patient_id=ready.patient.sysid)
    other = new_patient(ready, ready.b, full_name="Paciente de B")
    html = without_icons(
        page(ready.b.doctor, reverse("med_patients:detail", args=(ready.org_b.pk, other.sysid))).content.decode()
    )
    assert ALLERGY not in html and "Plano Resumo" not in html and ready.appointment.code not in html
    assert "Sem alergias registradas" not in html  # B's patient has no chart: the panel says so, it reads nothing of A.
    assert "ainda não tem prontuário" in html


def test_a_disabled_app_leaves_the_summary(ready, subtests):
    with subtests.test("finance"), ready.app_disabled("med_finance"):
        html = without_icons(page(ready.a.reception, summary_url(ready)).content.decode())
        assert "med_finance.balance" not in panels(html) and "Nova conta" not in html
        assert "med_scheduling.appointments" in panels(html)
    with subtests.test("records"), ready.app_disabled("med_records"):
        html = without_icons(page(ready.a.doctor, summary_url(ready)).content.decode())
        assert "med_records.allergies" not in panels(html) and ALLERGY not in html
    with subtests.test("scheduling and the apps on it"), ready.app_disabled("med_scheduling"):
        assert panel_codes(ready, ready.a.admin) == ["med_patients.coverage"]


def test_tabs_go_by_use(ready):
    with ready.as_user(ready.a.admin) as actor:
        tabs = [tab.code for tab in PatientService().page_tabs(actor=actor, patient_id=ready.patient.sysid)]
    assert tabs == [
        "summary",
        "med_scheduling.appointments",
        "med_records.chart",
        "med_finance.account",
        "registration",
        "guardians",
        "coverages",
        "consents",
        "timeline",
        "privacy",
    ]


def test_the_four_apps_show_the_same_patient_header(ready, subtests):
    org, patient = ready.org_a.pk, ready.patient.sysid
    pages = {
        "med_patients": (ready.a.reception, reverse("med_patients:detail", args=(org, patient))),
        "med_scheduling": (ready.a.reception, reverse("med_scheduling:patient_section", args=(org, patient))),
        "med_records": (ready.a.doctor, reverse("med_records:patient_section", args=(org, patient))),
        "med_finance": (ready.a.reception, reverse("med_finance:patient_section", args=(org, patient))),
    }
    headers = {}
    for app, (user, address) in pages.items():
        with subtests.test(app):
            response = page(user, address)
            assert response.status_code == 200
            html = without_icons(response.content.decode())
            header = re.search(r'<div class="page-header">.*?<nav class="link-tabs"', html, re.S).group(0)
            assert "<h1>Paciente do Resumo</h1>" in header and ready.patient.code in header
            assert "10 anos" in header and "Ativo" in header
            assert "Menor sem responsável legal cadastrado" in header  # The LGPD and minor warnings, in every app.
            headers[app] = re.search(r'<p class="page-eyebrow">.*?</h1>', header, re.S).group(0)
    assert len(set(headers.values())) == 1


def test_every_patient_tab_and_panel_title_shows_the_icon_of_its_concept(ready):
    """#144: the icon sits before the label, decorative, and the label is still there."""
    html = page(ready.a.doctor, summary_url(ready)).content.decode()
    nav = re.search(r'<nav class="link-tabs" aria-label="Seções do paciente">(.*?)</nav>', html, re.S).group(1)
    tabs = re.findall(r"<a [^>]*>(.*?)</a>", nav, re.S)
    assert len(tabs) >= 6
    assert all(re.match(r'<svg aria-hidden="true"[^>]*>.*</svg>[^<\s]', tab, re.S) for tab in tabs), tabs
    titles = re.findall(r'<h2 [^>]*class="section-heading patient-summary-heading">(.*?)</h2>', html, re.S)
    assert titles and all(title.startswith('<svg aria-hidden="true"') for title in titles)
