"""The clinic setup list: the steps of the active apps, done or pending, for administrators only."""

from django.test import Client
from django.urls import reverse

from ..service_api import PatientService
from .helpers import setup_registry


def test_clinic_setup_list(clinic):
    url = reverse("med_patients:clinic_setup", args=(clinic.org_a.pk,))
    admin = Client()
    admin.force_login(clinic.a.admin)
    with clinic.as_user(clinic.a.admin) as actor:
        before = {step.code: step.done for step in PatientService().setup_steps(actor=actor)}
    assert before["med_patients.registry"] is False
    assert [code for code in before][:4] == [
        "med_patients.registry",
        "med_scheduling.practice",
        "med_records.archives",
        "med_finance.desk",
    ]
    setup_registry(clinic)
    with clinic.as_user(clinic.a.admin) as actor:
        after = {step.code: step.done for step in PatientService().setup_steps(actor=actor)}
    assert after["med_patients.registry"] is True
    html = admin.get(url).content.decode()
    assert "Configuração da clínica" in html and reverse("med_finance:setup", args=(clinic.org_a.pk,)) in html
    reception = Client()
    reception.force_login(clinic.a.reception)
    assert reception.get(url).status_code == 404
