"""Recent photo counts, kept in memory and dropped after 30 minutes.

Each record is (timestamp, zone id, count). Nothing about the photo is stored.
The flow model stays the prior. A photo corrects it, and that correction fades
back to 1.0 over the same 30 minutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock

from app.assumptions import Assumptions
from app.graph import Graph
from app.model import Forecast, forecast as build_forecast
from app.models import Flight
from app.timeutil import require_aware

TTL = timedelta(minutes=30)
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 2.0

_lock = Lock()
_records: list[CountRecord] = []


@dataclass(frozen=True)
class CountRecord:
    ts: datetime
    zone_id: str
    count: int


def reset_counts() -> None:
    with _lock:
        _records.clear()


def remember_count(ts: datetime, zone_id: str, count: int) -> None:
    ts = require_aware(ts, "ts")
    if count < 0:
        raise ValueError("count must be zero or greater")
    with _lock:
        _expire(ts)
        _records.append(CountRecord(ts, zone_id, count))


def latest_counts(now: datetime) -> list[CountRecord]:
    """Newest count per zone that is still inside the 30-minute window."""
    now = require_aware(now, "now")
    with _lock:
        _expire(now)
        newest: dict[str, CountRecord] = {}
        for record in _records:
            current = newest.get(record.zone_id)
            if current is None or record.ts >= current.ts:
                newest[record.zone_id] = record
        return list(newest.values())


def _expire(now: datetime) -> None:
    cutoff = now - TTL
    _records[:] = [record for record in _records if record.ts > cutoff]


def raw_multiplier(photo_count: int, model_people: float) -> float:
    if model_people <= 1e-6:
        ratio = MAX_MULTIPLIER if photo_count > 0 else 1.0
    else:
        ratio = photo_count / model_people
    return min(MAX_MULTIPLIER, max(MIN_MULTIPLIER, ratio))


def decayed_multiplier(photo_count: int, model_people: float, age: timedelta) -> float:
    seconds = age.total_seconds()
    if seconds < 0 or seconds >= TTL.total_seconds():
        return 1.0
    raw = raw_multiplier(photo_count, model_people)
    remaining = 1.0 - seconds / TTL.total_seconds()
    return 1.0 + (raw - 1.0) * remaining


def _people_near(result: Forecast, zone_id: str, when: datetime) -> float:
    series = result.zone(zone_id).people
    if not series:
        return 0.0
    end = result.start + timedelta(minutes=result.bucket_minutes * (len(series) - 1))
    if when < result.start:
        when = result.start
    elif when > end:
        when = end
    return result.people_at(zone_id, when)


def zone_multipliers(prior: Forecast, now: datetime) -> dict[str, float]:
    now = require_aware(now, "now")
    multipliers: dict[str, float] = {}
    for record in latest_counts(now):
        try:
            people = _people_near(prior, record.zone_id, now)
        except KeyError:
            continue
        multipliers[record.zone_id] = decayed_multiplier(record.count, people, now - record.ts)
    return multipliers


def forecast_with_corrections(
    flights: list[Flight],
    graph: Graph,
    assumptions: Assumptions,
    start: datetime,
    hours: float,
    now: datetime,
) -> Forecast:
    """Run the flow model, then again with photo corrections when any are still fresh."""
    prior = build_forecast(flights, graph, assumptions, start, hours)
    multipliers = zone_multipliers(prior, now)
    if not multipliers:
        return prior
    return build_forecast(flights, graph, assumptions, start, hours, zone_multipliers=multipliers)
