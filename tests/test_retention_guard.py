"""The chart's legal retention vetoes deleting or anonymizing the patient."""

from datetime import timedelta

import pytest
from django.utils import timezone

from applications.med_patients.service_api import PatientService
from applications.med_records.models import PatientChart
from applications.med_records.tests.helpers import new_patient, open_chart, prepare
from skeleton.service_api import Conflict
from skeleton.tenancy.context import system_context


def _last_entry(chart, when, organization):
    with system_context(reason="test:retention", organization_id=organization.pk):
        row = PatientChart.objects.get(pk=chart.sysid)
        row.last_entry_at = when
        row.save(update_fields={"last_entry_at"})


def test_recent_chart_vetoes_anonymizing(clinic):
    ready = prepare(clinic)
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    with ready.as_user(ready.a.admin) as admin:
        current = PatientService().get(actor=admin, patient_id=patient.sysid)
    _last_entry(chart, timezone.now() - timedelta(days=30), ready.org_a)
    with ready.as_user(ready.a.admin) as admin, pytest.raises(Conflict) as error:
        PatientService().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=current.revision)
    assert "20 anos" in str(error.value.detail)

    _last_entry(chart, timezone.now() - timedelta(days=365 * 21), ready.org_a)
    with ready.as_user(ready.a.admin) as admin:
        PatientService().anonymize(actor=admin, patient_id=patient.sysid, expected_revision=current.revision)
