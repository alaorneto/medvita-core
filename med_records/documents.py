"""The five basic kinds of clinical document and the literal placeholder replacement (no template engine)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from django.utils.translation import gettext_lazy as _

from .extension import DocumentKind

PLACEHOLDERS = ("patient_name", "date", "professional_name")
_PLACEHOLDER = re.compile(r"\{\{\s*(" + "|".join(PLACEHOLDERS) + r")\s*\}\}")


def render_placeholders(body: str, values: Mapping[str, str]) -> str:
    """Replace the known ``{{name}}`` markers by their text; everything else stays literal.

    Only the names in ``PLACEHOLDERS`` are replaced, by plain substitution: no template engine,
    ``format`` or ``eval``, so ``{{ other }}``, ``{%`` and braces in the values stay as they are.
    """
    return _PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), match.group(0))), body)


BASIC_KINDS = (
    DocumentKind(
        "med_records.certificate",
        _("Atestado"),
        _("Atesto, para os devidos fins, que {{patient_name}} esteve sob meus cuidados em {{date}}."),
    ),
    DocumentKind(
        "med_records.attendance_statement",
        _("Declaração de comparecimento"),
        _("Declaro que {{patient_name}} compareceu a atendimento neste consultório em {{date}}."),
    ),
    DocumentKind(
        "med_records.simple_prescription",
        _("Receita simples"),
        _("Paciente: {{patient_name}}\n\nUso:\n\n"),
        notice=_("Receita simples: não serve para medicamentos sujeitos a controle especial."),
    ),
    DocumentKind(
        "med_records.exam_request",
        _("Pedido de exame"),
        _("Paciente: {{patient_name}}\n\nSolicito:\n\n"),
    ),
    DocumentKind(
        "med_records.referral",
        _("Encaminhamento"),
        _("Encaminho {{patient_name}} para avaliação.\n\nMotivo:\n\n"),
    ),
)
