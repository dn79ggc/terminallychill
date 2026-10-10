from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

CONCOURSES = ("T", "A", "B", "C", "D", "E", "F")
_GATE_LETTER = re.compile(r"^\s*([A-Za-z])")


def concourse_of(gate: str | None) -> str | None:
    """Concourse = first letter of the gate (B22 -> B). The provider 'terminal' is NOT used."""
    if not gate:
        return None
    m = _GATE_LETTER.match(gate)
    if not m:
        return None
    letter = m.group(1).upper()
    return letter if letter in CONCOURSES else None


def parse_dt(value: str | None) -> datetime | None:
    """ISO 8601 -> timezone-aware UTC datetime. Naive input is assumed to be UTC."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Flight:
    uid: str
    ident: str
    operator: str | None
    gate: str | None
    concourse: str | None
    terminal: str | None
    aircraft_type: str | None
    scheduled_out: datetime
    estimated_out: datetime | None
    delay_s: int | None
    cancelled: bool
    source: str
