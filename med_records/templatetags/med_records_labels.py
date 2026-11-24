"""Template filters of the records pages: labels of stored codes and the core state and marker of each one.

``{{ code|records_label:"allergy_status" }}`` is the translated label of a stored choice; ``records_state`` and
``records_marker`` give the core code of the tone this app chose, so ``status_badge`` and ``marker`` draw it.
"""

from django import template

from ..models import AccessLog, Allergy, EntryTemplate, Medication

register = template.Library()

CHOICES = {
    "allergy_category": Allergy.Category,
    "allergy_severity": Allergy.Severity,
    "allergy_status": Allergy.Status,
    "medication_status": Medication.Status,
    "access_action": AccessLog.Action,
    "template_kind": EntryTemplate.Kind,
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
    # An encounter and a document have no stored status: the page names the state from signed/issued/replaced.
    ("encounter", "draft"): "neutral",
    ("encounter", "signed"): "success",
    ("document", "draft"): "neutral",
    ("document", "issued"): "success",
    ("document", "replaced"): "neutral",
    ("allergy_status", "active"): "warning",
    ("allergy_status", "resolved"): "neutral",
    ("allergy_status", "refuted"): "neutral",
    ("medication_status", "active"): "brand",
    ("medication_status", "suspended"): "warning",
    ("medication_status", "ended"): "neutral",
}


@register.filter
def records_label(value: object, kind: str) -> str:
    """The translated label of a stored code: {{ item.status|records_label:"allergy_status" }}."""
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))


@register.filter
def records_state(value: object, kind: str) -> str:
    """The core state code with this app's tone: {{ code|records_state:"allergy_status"|status_badge:label }}."""
    return STATE_TONE_CODE[TONES.get((kind, str(value)), "neutral")]


@register.filter
def records_marker(tone: object) -> str:
    """The core marker code of a tone: {{ "neutral"|records_marker|marker:_("Pessoal") }}."""
    return MARKER_TONE_CODE.get(str(tone), "private")
