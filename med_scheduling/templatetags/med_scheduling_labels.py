"""Template filter that shows the translated label of a stored choice code (``{{ code|scheduling_label:"status" }}``)."""

from django import template

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


@register.filter
def scheduling_label(value: object, kind: str) -> str:
    choices = CHOICES.get(kind)
    if choices is None:
        return str(value)
    return str(dict(choices.choices).get(value, value))
