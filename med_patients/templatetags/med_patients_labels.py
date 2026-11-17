"""Template filter that shows the translated label of a stored choice code (``{{ code|patient_label:"sex" }}``)."""

from django import template

from ..models import Consent, Patient, PatientGuardian

register = template.Library()

CHOICES = {
    "sex": Patient.Sex,
    "status": Patient.Status,
    "contact_preference": Patient.ContactPreference,
    "relationship": PatientGuardian.Relationship,
    "consent_status": Consent.Status,
    "collected_via": Consent.CollectedVia,
}


@register.filter
def patient_label(value: object, kind: str) -> str:
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))
