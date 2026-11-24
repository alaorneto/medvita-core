"""Template filters of the patients app: labels of stored codes, tones of states and formatting of identifiers.

``{{ code|patient_label:"sex" }}`` shows the translated label of a stored choice code;
``{{ code|patient_state:"status"|status_badge:label }}`` gives a state the core code of this app's tone.
"""

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ..models import Consent, ImportBatch, Patient, PatientGuardian

register = template.Library()

CHOICES = {
    "sex": Patient.Sex,
    "status": Patient.Status,
    "contact_preference": Patient.ContactPreference,
    "relationship": PatientGuardian.Relationship,
    "consent_status": Consent.Status,
    "collected_via": Consent.CollectedVia,
    "import_status": ImportBatch.Status,
}

# The core's status_badge and marker read fixed maps (#121): a state or marker of this app is shown with a core code
# of the same tone and this app's own label. Tones: success concluído; brand em andamento; warning pede atenção;
# danger falhou ou é irreversível; neutral inativo, encerrado ou rascunho.
STATE_TONE_CODE = {
    "success": "completed",
    "brand": "running",
    "warning": "pending",
    "danger": "failed",
    "neutral": "withdrawn",
}
MARKER_TONE_CODE = {"brand": "primary", "warning": "locked", "neutral": "private"}
TONES = {
    ("status", "active"): "success",
    ("status", "inactive"): "neutral",
    ("status", "deceased"): "neutral",
    ("consent_status", "granted"): "success",
    ("consent_status", "revoked"): "neutral",
    ("import_status", "uploaded"): "brand",
    ("import_status", "validating"): "brand",
    ("import_status", "importing"): "brand",
    ("import_status", "validated"): "warning",  # Asks the person to start the import.
    ("import_status", "completed"): "success",
    ("import_status", "failed"): "danger",
}

# Why a row of a CSV import was not imported (jobs.validate_batch): "duplicate_cpf" or importer.error_code().
IMPORT_REASONS = {
    "duplicate_cpf": _("CPF já cadastrado ou repetido no arquivo"),
    "invalid": _("Linha recusada"),
    "invalid_full_name": _("Nome completo ausente ou longo demais"),
    "invalid_social_name": _("Nome social longo demais"),
    "invalid_birth_date": _("Data de nascimento inválida ou futura"),
    "invalid_sex": _("Sexo fora das opções"),
    "invalid_cpf": _("CPF inválido"),
    "invalid_national_health_card": _("Cartão Nacional de Saúde inválido"),
    "invalid_identity_document": _("Documento de identidade longo demais"),
    "invalid_mother_name": _("Nome da mãe longo demais"),
    "invalid_phone": _("Telefone inválido"),
    "invalid_phone_secondary": _("Outro telefone inválido"),
    "invalid_email": _("Email inválido"),
    "invalid_contact_preference": _("Preferência de contato fora das opções"),
    "invalid_postal_code": _("CEP inválido"),
    "invalid_street": _("Logradouro longo demais"),
    "invalid_number": _("Número do endereço longo demais"),
    "invalid_complement": _("Complemento longo demais"),
    "invalid_district": _("Bairro longo demais"),
    "invalid_city": _("Cidade longa demais"),
    "invalid_state": _("UF inválida"),
    "invalid_notes": _("Observações longas demais"),
}
# Why a whole import failed (jobs._fail).
IMPORT_FAILURES = {"forbidden": _("Quem enviou não pode mais alterar o cadastro.")}


@register.filter
def patient_label(value: object, kind: str) -> str:
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))


@register.filter
def patient_state(value: object, kind: str) -> str:
    """The core state code with this app's tone: {{ code|patient_state:"status"|status_badge:label }}."""
    return STATE_TONE_CODE[TONES.get((kind, str(value)), "neutral")]


@register.filter
def patient_marker(tone: object) -> str:
    """The core marker code of a tone: {{ "brand"|patient_marker|marker:_("Principal") }}."""
    return MARKER_TONE_CODE.get(str(tone), "private")


@register.filter
def patient_purpose(code: object, labels: object) -> str:
    """The label of a consent purpose; a purpose of an app no longer active keeps its code for the support."""
    label = labels.get(str(code)) if isinstance(labels, dict) else None
    if label:
        return str(label)
    return format_html('{} <code class="uuid" translate="no">{}</code>', gettext("Finalidade não disponível"), code)


@register.filter
def patient_import_reason(code: object) -> str:
    """Why a row was not imported; an unknown code reads "Linha recusada" with the code on a second line."""
    label = IMPORT_REASONS.get(str(code))
    if label:
        return str(label)
    return format_html(
        '{}<span class="cell-secondary"><code class="uuid" translate="no">{}</code></span>',
        gettext("Linha recusada"),
        code,
    )


@register.filter
def patient_import_failure(code: object) -> str:
    """Why an import failed; an unknown code reads as a generic sentence with the code for the support."""
    label = IMPORT_FAILURES.get(str(code))
    if label:
        return str(label)
    return format_html(
        '{} <code class="uuid" translate="no">{}</code>', gettext("Não foi possível concluir a importação."), code
    )


@register.filter
def patient_section_title(title: object) -> str:
    """The name of the app that wrote a section of the data subject report (its code is the app label)."""
    from django.apps import apps

    try:
        return str(apps.get_app_config(str(title)).verbose_name)
    except LookupError:
        return str(title)


def _digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


@register.filter
def patient_cpf(value: object) -> str:
    """11 digits as 000.000.000-00; anything else as it is."""
    text = str(value or "")
    if len(text) == 11 and text.isdigit():
        return f"{text[:3]}.{text[3:6]}.{text[6:9]}-{text[9:]}"
    return text


@register.filter
def patient_phone(value: object) -> str:
    """10 or 11 digits as (00) 0000-0000 / (00) 00000-0000, with a +55 kept in front; anything else as it is."""
    text = str(value or "")
    prefix, number = ("+55 ", text[3:]) if text.startswith("+55") else ("", text)
    if number.isdigit() and len(number) in (10, 11):
        return f"{prefix}({number[:2]}) {number[2:-4]}-{number[-4:]}"
    return text


def _postal_code(value: str) -> str:
    return f"{value[:5]}-{value[5:]}" if len(value) == 8 and value.isdigit() else value


@register.filter
def patient_address(patient: object) -> str:
    """The address on one line: "Rua X, 12, apto 3 · Bairro · Cidade/UF · CEP 00000-000"; "—" when empty."""

    def field(name: str) -> str:
        return str(getattr(patient, name, "") or "").strip()

    street = ", ".join(part for part in (field("street"), field("number"), field("complement")) if part)
    city = "/".join(part for part in (field("city"), field("state")) if part)
    postal = field("postal_code")
    parts = [
        street,
        field("district"),
        city,
        gettext("CEP %(code)s") % {"code": _postal_code(postal)} if postal else "",
    ]
    return " · ".join(part for part in parts if part) or "—"


@register.filter
def patient_contacts(patient: object) -> str:
    """Phones and email on one line, separated by " · " (the printed report); "—" when there is none."""
    phones = [patient_phone(getattr(patient, name, "")) for name in ("phone", "phone_secondary")]
    parts = [*phones, str(getattr(patient, "email", "") or "")]
    return " · ".join(part for part in parts if part) or "—"
