"""Validation of structured sections and the seven basic section types (pure functions, no ORM)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from skeleton.service_api import InvalidInput

from .extension import SectionField, SectionType

TEXT_LIMIT = 500
LONG_TEXT_LIMIT = 20_000
FREE_TEXT_LIMIT = 50_000
ICD10_CODE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,2})?$")
ICD10_LIMIT = 20


def _error(name: str, message: str) -> InvalidInput:
    return InvalidInput({f"data.{name}": [message]})


def _decimal(field: SectionField, value: Any) -> str:
    if isinstance(value, bool):
        raise _error(field.name, gettext("Informe um número."))
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise _error(field.name, gettext("Informe um número.")) from None
    if not number.is_finite():
        raise _error(field.name, gettext("Informe um número."))
    _range(field, number)
    return format(number.normalize(), "f")


def _range(field: SectionField, number: Any) -> None:
    if (field.min is not None and number < Decimal(str(field.min))) or (
        field.max is not None and number > Decimal(str(field.max))
    ):
        raise _error(field.name, gettext("Valor fora da faixa aceita."))


def _integer(field: SectionField, value: Any) -> int:
    if isinstance(value, bool):
        raise _error(field.name, gettext("Informe um número inteiro."))
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,9}", value.strip()):
        value = int(value.strip())
    if type(value) is not int:
        raise _error(field.name, gettext("Informe um número inteiro."))
    _range(field, Decimal(value))
    return value


def _text(field: SectionField, value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise _error(field.name, gettext("Informe um texto."))
    if len(value) > limit:
        raise _error(field.name, gettext("Texto longo demais."))
    return value


def _icd10_list(field: SectionField, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple) or len(value) > ICD10_LIMIT:
        raise _error(field.name, gettext("Informe até 20 diagnósticos."))
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"code", "description", "primary"}:
            raise _error(field.name, gettext("Cada diagnóstico tem código, descrição e se é o principal."))
        code = str(item.get("code") or "").strip().upper()
        description = str(item.get("description") or "").strip()
        if not ICD10_CODE.fullmatch(code):
            raise _error(field.name, gettext("Código CID-10 inválido."))
        if len(description) > 300:
            raise _error(field.name, gettext("Descrição longa demais."))
        result.append({"code": code, "description": description, "primary": item.get("primary") is True})
    if sum(1 for item in result if item["primary"]) > 1:
        raise _error(field.name, gettext("Só um diagnóstico pode ser o principal."))
    return result


def _value(field: SectionField, value: Any) -> Any:
    if field.kind == "text":
        return _text(field, value, TEXT_LIMIT)
    if field.kind == "long_text":
        return _text(field, value, LONG_TEXT_LIMIT)
    if field.kind == "integer":
        return _integer(field, value)
    if field.kind == "decimal":
        return _decimal(field, value)
    if field.kind == "boolean":
        if value in (True, False, "true", "false", "1", "0", "on"):
            return value in (True, "true", "1", "on")
        raise _error(field.name, gettext("Informe sim ou não."))
    if field.kind == "choice":
        if value not in {code for code, _label in field.choices}:
            raise _error(field.name, gettext("Escolha uma das opções."))
        return value
    if field.kind == "date":
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise _error(field.name, gettext("Use uma data válida (AAAA-MM-DD).")) from None
    return _icd10_list(field, value)


def _empty(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, list | tuple) and not value)
    )


def validate_section(section_type: SectionType, data: Any, text: Any = "") -> tuple[dict[str, Any], str]:
    """The normalized structured data and free text of a section, or ``InvalidInput`` naming the field.

    Unknown keys, wrong types and values out of range are refused; empty optional values are
    dropped. Decimals become text with a dot, so the stored JSON is stable.
    """
    if not isinstance(data, dict):
        raise InvalidInput({"data": [gettext("Os dados da seção são um objeto.")]})
    known = {field.name: field for field in section_type.fields}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise InvalidInput({f"data.{name}": [gettext("Campo desconhecido nesta seção.")] for name in unknown})
    clean: dict[str, Any] = {}
    for name, field in known.items():
        value = data.get(name)
        if _empty(value):
            if field.required:
                raise _error(name, gettext("Campo obrigatório."))
            continue
        clean[name] = _value(field, value)
    if not isinstance(text, str) or len(text) > FREE_TEXT_LIMIT:
        raise InvalidInput({"text": [gettext("Texto longo demais.")]})
    if text and not section_type.has_text:
        raise InvalidInput({"text": [gettext("Esta seção não aceita texto livre.")]})
    return clean, text


def body_mass_index(data: dict[str, Any]) -> str:
    """BMI shown next to the vital signs (never stored): weight (kg) / height (m)²."""
    try:
        weight = Decimal(str(data["weight"]))
        height = Decimal(str(data["height"])) / 100
    except (KeyError, InvalidOperation):
        return ""
    if height <= 0:
        return ""
    return format((weight / (height * height)).quantize(Decimal("0.1")), "f")


BASIC_TYPES = (
    SectionType(
        "med_records.anamnesis",
        _("Anamnese"),
        (
            SectionField("chief_complaint", _("Queixa principal"), "text"),
            SectionField("history", _("História da doença atual"), "long_text"),
            SectionField("past_history", _("Antecedentes pessoais"), "long_text"),
            SectionField("family_history", _("Antecedentes familiares"), "long_text"),
            SectionField("habits", _("Hábitos de vida"), "long_text"),
        ),
    ),
    SectionType(
        "med_records.vitals",
        _("Sinais vitais"),
        (
            SectionField("systolic", _("Pressão sistólica"), "integer", unit="mmHg", min=30, max=300),
            SectionField("diastolic", _("Pressão diastólica"), "integer", unit="mmHg", min=20, max=200),
            SectionField("heart_rate", _("Frequência cardíaca"), "integer", unit="bpm", min=20, max=300),
            SectionField("respiratory_rate", _("Frequência respiratória"), "integer", unit="irpm", min=4, max=80),
            SectionField("temperature", _("Temperatura"), "decimal", unit="°C", min=30, max=45),
            SectionField("spo2", _("Saturação de oxigênio"), "integer", unit="%", min=50, max=100),
            SectionField("weight", _("Peso"), "decimal", unit="kg", min=0.3, max=500),
            SectionField("height", _("Altura"), "integer", unit="cm", min=20, max=260),
            SectionField("glucose", _("Glicemia capilar"), "integer", unit="mg/dL", min=10, max=1000),
        ),
    ),
    SectionType("med_records.physical_exam", _("Exame físico")),
    SectionType(
        "med_records.assessment",
        _("Hipóteses diagnósticas"),
        (SectionField("diagnoses", _("Diagnósticos (CID-10)"), "icd10_list"),),
    ),
    SectionType("med_records.plan", _("Conduta")),
    SectionType(
        "med_records.evolution",
        _("Evolução (SOAP)"),
        (
            SectionField("subjective", _("Subjetivo"), "long_text"),
            SectionField("objective", _("Objetivo"), "long_text"),
            SectionField("assessment", _("Avaliação"), "long_text"),
            SectionField("plan", _("Plano"), "long_text"),
        ),
        has_text=False,
    ),
    SectionType("med_records.free_text", _("Texto livre")),
)
