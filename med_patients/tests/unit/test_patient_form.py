"""The patient form in four groups, its optional masks and the way back to the booking page (no database)."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.test import RequestFactory
from django.utils import timezone

from ...forms import GuardianForm, PatientForm
from ...templatetags.med_patients_labels import patient_coverage_due, patient_days_left
from ...views import booking_return, with_patient

# Fixed ids: the parametrized ids below must be the same in every pytest-xdist worker.
ORG = UUID("00000000-0000-4000-8000-0000000000a1")
OTHER_ORG = UUID("00000000-0000-4000-8000-0000000000b2")
BOOK = f"/o/{ORG}/apps/med_scheduling/book/"


def test_the_form_comes_in_four_groups_with_every_field_once():
    form = PatientForm()
    groups = form.groups()
    assert [str(legend) for legend, _fields in groups] == ["Identificação", "Contato", "Endereço", "Observações"]
    names = [field.name for _legend, fields in groups for field in fields]
    assert sorted(names) == sorted(form.fields) and len(names) == len(set(names))
    assert [field.name for field in groups[3][1]] == ["notes"]


def test_the_masks_are_only_marks_for_the_optional_script():
    form = PatientForm()
    marks = {name: field.widget.attrs.get("data-mask") for name, field in form.fields.items()}
    assert {name: mask for name, mask in marks.items() if mask} == {
        "cpf": "cpf",
        "phone": "phone",
        "phone_secondary": "phone",
        "postal_code": "cep",
    }
    # The widths fit the masked text; the server normalizes either way.
    assert form.fields["cpf"].max_length >= len("529.982.247-25")
    assert form.fields["postal_code"].max_length >= len("50000-000")
    assert form.fields["phone"].max_length >= len("(11) 98888-7777")
    guardian = GuardianForm()
    assert guardian.fields["cpf"].widget.attrs["data-mask"] == "cpf"
    assert guardian.fields["phone"].widget.attrs["data-mask"] == "phone"


def back(value, method="get"):
    request = getattr(RequestFactory(), method)("/", {"next": value})
    return booking_return(request, ORG)


def test_a_booking_path_of_the_organization_is_accepted():
    path = f"{BOOK}?schedule=1&day=2026-11-25&start=09%3A00"
    assert back(path) == path
    assert back(path, "post") == path
    assert back(BOOK) == BOOK


@pytest.mark.parametrize(
    "value",
    (
        "",
        "https://evil.example/",
        f"https://evil.example{BOOK}",
        "//evil.example/",
        f"//evil.example{BOOK}",
        f"/\\evil.example{BOOK}",
        f"/o/{ORG}/apps/med_records/",
        f"/o/{OTHER_ORG}/apps/med_scheduling/book/",
        f"{BOOK}../../med_records/",
        f"{BOOK}%2e%2e/%2e%2e/med_records/",
        f"{BOOK}/..//evil.example",
        f"javascript:alert(1)//{BOOK}",
        f"{BOOK}\nLocation: //evil.example",
    ),
)
def test_any_other_way_back_is_ignored(value):
    assert back(value) == ""


def test_the_way_back_carries_the_patient_and_keeps_the_other_parameters():
    patient = uuid4()
    url = with_patient(f"{BOOK}?schedule=1&day=2026-11-25&start=09%3A00&patient=old", patient)
    assert url == f"{BOOK}?schedule=1&day=2026-11-25&start=09%3A00&patient={patient}"
    assert with_patient(BOOK, patient) == f"{BOOK}?patient={patient}"


def test_days_left_of_a_coverage():
    today = timezone.localdate()
    assert patient_days_left(today - timedelta(days=1)) == -1
    assert patient_days_left(today + timedelta(days=10)) == 10
    assert patient_days_left(None) is None
    assert patient_coverage_due(0) and patient_coverage_due(30)
    assert not patient_coverage_due(31) and not patient_coverage_due(-1) and not patient_coverage_due(None)
