"""The read trail of the chart: who read clinical content, when (filled by the read-trail issue)."""

from __future__ import annotations

from typing import Any


def record_access(actor: Any, chart: Any, action: str, target: Any = None) -> None:
    """Record a read of clinical content, after it was authorized. No-op until the trail table exists."""
    return None
