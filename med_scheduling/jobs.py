"""Jobs of the scheduling app."""

from __future__ import annotations

from django.utils import timezone


def expire_waitlist() -> int:
    """Mark as expired the waiting entries whose last date passed (one organization per job).

    Runs in the system context of one organization, as the core periodic scheduler enqueues it;
    idempotent: an expired entry is never touched again.
    """
    from .models import WaitlistEntry

    today = timezone.localdate()
    expired = 0
    for entry in WaitlistEntry.objects.filter(status=WaitlistEntry.Status.WAITING, latest_date__lt=today):
        entry.status = WaitlistEntry.Status.EXPIRED
        entry.save(update_fields={"status"})
        expired += 1
    return expired
