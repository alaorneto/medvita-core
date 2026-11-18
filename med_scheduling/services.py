"""Internal rules of the scheduling app. Only ``service_api.py`` (and its jobs and consumers) call this."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext

from skeleton.service_api import InvalidInput

from . import validators
from .models import COLORS, AppointmentType, Professional, Room

PRACTICE_FIELDS = ("name", "legal_name", "tax_id", "phone", "email", "address", "city", "state", "timezone")
PROFESSIONAL_FIELDS = ("display_name", "council", "council_number", "council_state", "specialty", "rqe", "tax_id")
ROOM_FIELDS = ("name", "kind", "is_active")
TYPE_FIELDS = ("name", "duration_minutes", "color", "billing_code", "requires_room", "is_active")
LIMITS = {
    "name": 120,
    "legal_name": 200,
    "phone": 20,
    "address": 300,
    "city": 80,
    "display_name": 200,
    "council_number": 20,
    "specialty": 120,
    "rqe": 20,
    "billing_code": 40,
}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _limit(values: dict[str, Any], errors: dict[str, list[str]]) -> None:
    for name, size in LIMITS.items():
        if name in values and isinstance(values[name], str) and len(values[name]) > size:
            errors[name] = [gettext("Texto longo demais.")]


def clean_practice(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for name, raw in values.items():
        if name == "tax_id":
            clean[name] = validators.digits(raw)
            if not validators.valid_tax_id(clean[name]):
                errors[name] = [gettext("CPF ou CNPJ inválido.")]
        elif name == "state":
            clean[name] = _text(raw).upper()
            if not validators.valid_state(clean[name]):
                errors[name] = [gettext("UF inválida.")]
        elif name == "timezone":
            clean[name] = _text(raw)
            if not validators.valid_timezone(clean[name]):
                errors[name] = [gettext("Fuso horário desconhecido.")]
        elif name == "email":
            clean[name] = _text(raw).lower()
        else:
            clean[name] = _text(raw)
    if (not partial or "name" in values) and not clean.get("name"):
        errors["name"] = [gettext("Informe o nome do consultório.")]
    _limit(clean, errors)
    if errors:
        raise InvalidInput(errors)
    return clean


def clean_professional(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for name, raw in values.items():
        if name == "tax_id":
            clean[name] = validators.digits(raw)
            if clean[name] and not validators.valid_cpf(clean[name]):
                errors[name] = [gettext("CPF inválido.")]
        elif name == "council":
            clean[name] = _text(raw) or Professional.Council.CRM
            if clean[name] not in Professional.Council.values:
                errors[name] = [gettext("Escolha um conselho.")]
        elif name == "council_state":
            clean[name] = _text(raw).upper()
            if not validators.valid_state(clean[name]):
                errors[name] = [gettext("UF inválida.")]
        else:
            clean[name] = _text(raw)
    if (not partial or "display_name" in values) and not clean.get("display_name"):
        errors["display_name"] = [gettext("Informe o nome do profissional.")]
    _limit(clean, errors)
    if errors:
        raise InvalidInput(errors)
    return clean


def clean_room(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    if "name" in values or not partial:
        clean["name"] = _text(values.get("name"))
        if not clean["name"] or len(clean["name"]) > 80:
            errors["name"] = [gettext("Informe o nome (até 80 caracteres).")]
    if "kind" in values or not partial:
        clean["kind"] = _text(values.get("kind")) or Room.Kind.ROOM
        if clean["kind"] not in Room.Kind.values:
            errors["kind"] = [gettext("Escolha sala ou equipamento.")]
    if "is_active" in values:
        clean["is_active"] = bool(values["is_active"])
    if errors:
        raise InvalidInput(errors)
    return clean


def clean_type(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    import re

    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    if "code" in values:
        clean["code"] = _text(values["code"]).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", clean["code"]):
            errors["code"] = [gettext("Use letras minúsculas, dígitos, hífen ou sublinhado (até 40).")]
    for name in ("name", "billing_code", "color"):
        if name in values or (not partial and name != "billing_code"):
            clean[name] = _text(values.get(name))
    if "color" in clean:
        clean["color"] = clean["color"] or "blue"
        if clean["color"] not in COLORS:
            errors["color"] = [gettext("Cor desconhecida.")]
    if "duration_minutes" in values or not partial:
        duration = values.get("duration_minutes", 30)
        if type(duration) is not int or not 5 <= duration <= 480:
            errors["duration_minutes"] = [gettext("Use de 5 a 480 minutos.")]
        clean["duration_minutes"] = duration
    for name in ("requires_room", "is_active"):
        if name in values:
            clean[name] = bool(values[name])
    if (not partial or "name" in values) and not clean.get("name"):
        errors["name"] = [gettext("Informe o nome do tipo de atendimento.")]
    if not partial and "code" not in values:
        errors["code"] = [gettext("Informe o código.")]
    _limit(clean, errors)
    if errors:
        raise InvalidInput(errors)
    return clean


__all__ = ["AppointmentType", "Room"]
