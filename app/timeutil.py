from __future__ import annotations

from datetime import datetime, timezone


def require_aware(value: datetime, label: str) -> datetime:
    """Reject naive datetimes. All computation stays in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    value = require_aware(value, "timestamp")
    return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
