"""Personal, health and money fields open the right keyboard and stay out of the browser's history (#120)."""

import pytest


@pytest.mark.parametrize(
    ("factory", "name", "expected"),
    [
        ("med_patients.forms:PatientForm", "cpf", {"inputmode": "numeric", "autocomplete": "off"}),
        ("med_patients.forms:PatientForm", "national_health_card", {"inputmode": "numeric"}),
        ("med_patients.forms:PatientForm", "postal_code", {"inputmode": "numeric"}),
        ("med_patients.forms:PatientForm", "phone", {"type": "tel", "autocomplete": "off"}),
        ("med_patients.forms:PatientForm", "email", {"spellcheck": "false", "autocomplete": "off"}),
        ("med_patients.forms:PatientForm", "full_name", {"autocomplete": "off"}),
        ("med_patients.forms:GuardianForm", "phone", {"type": "tel", "autocomplete": "off"}),
        ("med_finance.forms:PaymentForm", "amount", {"inputmode": "decimal", "autocomplete": "off"}),
        ("med_finance.forms:CloseSessionForm", "counted_amount", {"inputmode": "decimal"}),
        ("med_finance.forms:PaymentForm", "authorization_code", {"spellcheck": "false"}),
        ("med_scheduling.forms:PracticeForm", "phone", {"type": "tel"}),
    ],
)
def test_the_widget_says_what_the_field_holds(factory, name, expected):
    from importlib import import_module

    module, _sep, cls = factory.partition(":")
    form = getattr(import_module(f"applications.{module}"), cls)()
    html = str(form[name])
    for attribute, value in expected.items():
        assert f'{attribute}="{value}"' in html, (factory, name, attribute, html)
