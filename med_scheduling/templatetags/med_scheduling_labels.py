"""Template filters of the scheduling pages.

``{{ code|scheduling_label:"status" }}`` shows the translated label of a stored choice code; the tone filters
give the core's ``status_badge`` and ``marker`` a code of the same tone (#121); the date filters write a
day out for headings and column heads (#122).
"""

from datetime import date, datetime

from django import template
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.html import format_html
from django.utils.text import capfirst

from ..models import Appointment, Modality, Mode, PaymentKind, Room, ScheduleBlock, WaitlistEntry

register = template.Library()

CHOICES = {
    "status": Appointment.Status,
    "mode": Mode,
    "modality": Modality,
    "payment_kind": PaymentKind,
    "cancel_reason": Appointment.CancelReason,
    "room_kind": Room.Kind,
    "block_reason": ScheduleBlock.Reason,
    "period": WaitlistEntry.Period,
    "priority": WaitlistEntry.Priority,
    "waitlist_status": WaitlistEntry.Status,
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
    ("status", "scheduled"): "neutral",
    ("status", "confirmed"): "success",
    ("status", "arrived"): "warning",
    ("status", "in_progress"): "brand",
    ("status", "completed"): "success",
    ("status", "no_show"): "danger",
    ("status", "cancelled"): "neutral",
    ("waitlist_status", "waiting"): "warning",
    ("waitlist_status", "booked"): "success",
    ("waitlist_status", "cancelled"): "neutral",
    ("waitlist_status", "expired"): "neutral",
}


@register.filter
def scheduling_label(value: object, kind: str) -> str:
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))


@register.filter
def scheduling_state(value: object, kind: str) -> str:
    """The core state code with this app's tone: {{ code|scheduling_state:"status"|status_badge:label }}."""
    return STATE_TONE_CODE[TONES.get((kind, str(value)), "neutral")]


@register.filter
def scheduling_marker(tone: object) -> str:
    """The core marker code of a tone: {{ "warning"|scheduling_marker|marker:_("Encaixe") }}."""
    return MARKER_TONE_CODE.get(str(tone), "private")


def _day(value: date) -> date:
    """The day of a date or of an instant, on the active clock (the practice's, on every scheduling page)."""
    if isinstance(value, datetime):
        return (timezone.localtime(value) if timezone.is_aware(value) else value).date()
    return value


@register.filter
def scheduling_long_date(value: object, case: str = "") -> str:
    """A heading date written out, in a <time>: "Terça-feira, 24/11/2026".

    The first letter is a capital, for a heading or the start of a line; ``"inline"`` keeps the weekday in lower
    case, as in the middle of a sentence ("Agenda de terça-feira, 24/11/2026").
    """
    if not isinstance(value, date):
        return "—"
    day = _day(value)
    text = date_format(day, "l, d/m/Y")
    text = text[:1].lower() + text[1:] if case == "inline" else capfirst(text)
    return format_html('<time datetime="{}">{}</time>', day.isoformat(), text)


@register.filter
def scheduling_short_weekday(value: object) -> str:
    """A column head of a day, in a <time>: "Seg 24/11"."""
    if not isinstance(value, date):
        return "—"
    day = _day(value)
    return format_html('<time datetime="{}">{}</time>', day.isoformat(), capfirst(date_format(day, "D d/m")))
