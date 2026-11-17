"""Internal rules of the patients app. Only ``service_api.py`` (and the gateway operations) call this."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext

from skeleton.tenancy.context import current_context

from . import validators
from .models import Patient, PatientRegistry

# Fields a person may write through PatientService.create/update; code, registry, status,
# anonymization and the processing restriction have their own operations.
WRITABLE_FIELDS = (
    "full_name",
    "social_name",
    "birth_date",
    "sex",
    "cpf",
    "national_health_card",
    "identity_document",
    "mother_name",
    "phone",
    "phone_secondary",
    "email",
    "contact_preference",
    "postal_code",
    "street",
    "number",
    "complement",
    "district",
    "city",
    "state",
    "notes",
)
TEXT_LIMITS = {
    "full_name": 200,
    "social_name": 200,
    "identity_document": 30,
    "mother_name": 200,
    "street": 120,
    "number": 20,
    "complement": 60,
    "district": 80,
    "city": 80,
    "notes": 4000,
}


def deterministic_id(kind: str, actor: Any, idempotency_key: str) -> uuid.UUID:
    """The sysid a repeatable creation gets from its idempotency key (same actor, same organization)."""
    organization = current_context().organization_id
    return uuid.uuid5(uuid.NAMESPACE_URL, f"med-patients:{kind}:{organization}:{actor.pk}:{idempotency_key}")


def update_registry_record(record: PatientRegistry, *, user: Any, values: dict[str, Any]) -> None:
    """Generic gateway update of a registry: only the name (the spec's write_fields)."""
    from django.core.exceptions import ValidationError

    name = str(values.get("name", record.name)).strip()
    if not name:
        raise ValidationError({"name": gettext("Informe o nome do cadastro.")})
    record.name = name
    record.save(update_fields={"name"})


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _date(value: object, field: str, errors: dict[str, list[str]]) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors[field] = [gettext("Use uma data válida (AAAA-MM-DD).")]
        return None


def clean_patient_values(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """Normalize and validate patient fields; errors name the field, never echo its value.

    ``partial`` validates only the fields given (an update); otherwise ``full_name`` is required.
    """
    from skeleton.service_api import InvalidInput

    errors: dict[str, list[str]] = {}
    unknown = sorted(set(values) - set(WRITABLE_FIELDS))
    for name in unknown:
        errors[name] = [gettext("Campo não pode ser alterado por esta operação.")]
    clean: dict[str, Any] = {}
    for name, raw in values.items():
        if name in unknown:
            continue
        if name == "birth_date":
            value = _date(raw, name, errors)
            if value is not None and value > timezone.localdate():
                errors[name] = [gettext("A data de nascimento não pode ser futura.")]
            clean[name] = value
        elif name == "cpf":
            value = validators.digits(raw)
            if value and not validators.valid_cpf(value):
                errors[name] = [gettext("CPF inválido.")]
            clean[name] = value
        elif name == "national_health_card":
            value = validators.digits(raw)
            if value and not validators.valid_cns(value):
                errors[name] = [gettext("Cartão Nacional de Saúde inválido.")]
            clean[name] = value
        elif name in ("phone", "phone_secondary"):
            value = validators.normalize_phone(raw)
            if not validators.valid_phone(value):
                errors[name] = [gettext("Telefone inválido: use DDD e número, com DDI opcional.")]
            clean[name] = value
        elif name == "postal_code":
            value = validators.digits(raw)
            if not validators.valid_postal_code(value):
                errors[name] = [gettext("CEP inválido: use 8 dígitos.")]
            clean[name] = value
        elif name == "state":
            value = _text(raw).upper()
            if not validators.valid_state(value):
                errors[name] = [gettext("UF inválida.")]
            clean[name] = value
        elif name == "email":
            value = _text(raw).lower()
            if value:
                from django.core.exceptions import ValidationError
                from django.core.validators import validate_email

                try:
                    validate_email(value)
                except ValidationError:
                    errors[name] = [gettext("Email inválido.")]
            clean[name] = value
        elif name == "sex":
            value = _text(raw) or Patient.Sex.UNKNOWN
            if value not in Patient.Sex.values:
                errors[name] = [gettext("Escolha uma das opções.")]
            clean[name] = value
        elif name == "contact_preference":
            value = _text(raw) or Patient.ContactPreference.PHONE
            if value not in Patient.ContactPreference.values:
                errors[name] = [gettext("Escolha uma das opções.")]
            clean[name] = value
        else:
            value = _text(raw)
            if len(value) > TEXT_LIMITS.get(name, 200):
                errors[name] = [gettext("Texto longo demais.")]
            clean[name] = value
    if not partial or "full_name" in values:
        if not clean.get("full_name"):
            errors["full_name"] = [gettext("Informe o nome completo.")]
    if errors:
        raise InvalidInput(errors)
    return clean


def apply_search_name(patient: Patient) -> None:
    patient.search_name = validators.search_name(patient.full_name, patient.social_name)


def search_filter(query: str) -> tuple[str, str]:
    """How a free-text query is matched: ``("cpf", value)``, ``("code", ...)``, ``("phone", ...)`` or ``("name", ...)``."""
    text = (query or "").strip()
    plain = validators.digits(text)
    if len(plain) == 11 and len(text.replace(".", "").replace("-", "").replace(" ", "")) == 11:
        return "cpf", plain
    if text[:1] in "Pp" and text[1:].isdigit():
        return "code", "P" + text[1:].zfill(6)
    if plain and len(plain) >= 8 and plain == text.replace("(", "").replace(")", "").replace(" ", "").replace("-", ""):
        return "phone", plain
    return "name", validators.normalize_name(text)
