"""Charts: one per archive and patient, isolated between organizations, invisible without the archive."""

import pytest

from skeleton.service_api import NotFound

from ..service_api import RecordsService
from .helpers import new_patient, open_chart, prepare


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


def test_open_chart_is_get_or_create(ready):
    patient = new_patient(ready)
    first = open_chart(ready, patient)
    again = open_chart(ready, patient)
    assert first.sysid == again.sysid and first.writable and first.last_entry_at is None
    with ready.as_user(ready.a.doctor) as doctor:
        (only,) = RecordsService().charts_for_patient(actor=doctor, patient_id=patient.sysid)
        assert only.sysid == first.sysid


def test_other_organization_sees_nothing(ready):
    patient = new_patient(ready)
    chart = open_chart(ready, patient)
    with ready.as_user(ready.b.doctor, ready.org_b) as outsider:
        with pytest.raises(NotFound):
            RecordsService().chart(actor=outsider, chart_id=chart.sysid)
        assert RecordsService().charts_for_patient(actor=outsider, patient_id=patient.sysid) == ()
        with pytest.raises(NotFound):
            RecordsService().open_chart(actor=outsider, patient_id=patient.sysid)


def test_patient_the_actor_cannot_read(ready):
    with ready.as_user(ready.a.doctor) as doctor, pytest.raises(NotFound):
        RecordsService().open_chart(actor=doctor, patient_id="00000000-0000-0000-0000-000000000001")
