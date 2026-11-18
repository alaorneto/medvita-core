"""Internal rules of the records app: cleaning of the clinical lists (never imported by other apps)."""

from __future__ import annotations

import unicodedata
from datetime import date
from typing import Any

from django.utils.translation import gettext

from skeleton.service_api import InvalidInput

from .models import Allergy, Medication

ALLERGY_FIELDS = ("substance", "category", "reaction", "severity", "status", "noted_on")
MEDICATION_FIELDS = ("name", "dose", "route", "frequency", "started_on", "ended_on", "status", "note")


def _text(errors: dict, values: dict, name: str, limit: int, *, required: bool = False) -> None:
    if name not in values:
        return
    value = values[name]
    if not isinstance(value, str) or len(value.strip()) > limit:
        errors[name] = [gettext("Use um texto de até %(limit)s caracteres.") % {"limit": limit}]
        return
    values[name] = value.strip()
    if required and not values[name]:
        errors[name] = [gettext("Campo obrigatório.")]


def _choice(errors: dict, values: dict, name: str, choices: Any) -> None:
    if name in values and values[name] not in choices.values:
        errors[name] = [gettext("Escolha uma das opções.")]


def _date(errors: dict, values: dict, name: str) -> None:
    if name in values and values[name] is not None and not isinstance(values[name], date):
        errors[name] = [gettext("Informe uma data.")]


def clean_allergy(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    values = dict(values)
    errors: dict[str, list[str]] = {}
    _text(errors, values, "substance", 200, required=True)
    _text(errors, values, "reaction", 300)
    _choice(errors, values, "category", Allergy.Category)
    _choice(errors, values, "severity", Allergy.Severity)
    _choice(errors, values, "status", Allergy.Status)
    _date(errors, values, "noted_on")
    if not partial and "substance" not in values:
        errors["substance"] = [gettext("Campo obrigatório.")]
    if errors:
        raise InvalidInput(errors)
    return values


def clean_medication(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    values = dict(values)
    errors: dict[str, list[str]] = {}
    _text(errors, values, "name", 200, required=True)
    _text(errors, values, "dose", 80)
    _text(errors, values, "route", 40)
    _text(errors, values, "frequency", 120)
    _text(errors, values, "note", 300)
    _choice(errors, values, "status", Medication.Status)
    _date(errors, values, "started_on")
    _date(errors, values, "ended_on")
    if not partial and "name" not in values:
        errors["name"] = [gettext("Campo obrigatório.")]
    if errors:
        raise InvalidInput(errors)
    return values


def fold(value: str) -> str:
    """Lower case without accents, for searching the ICD-10 descriptions."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).lower().split())
