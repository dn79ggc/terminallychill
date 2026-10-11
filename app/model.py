"""Flow-model crowd index. Pure function: flights in, forecast out. No database."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.assumptions import Assumptions, seats_for
from app.graph import Graph
from app.models import Flight
from app.timeutil import iso_z, require_aware

BUCKET_MINUTES = 5


@dataclass(frozen=True)
class ZoneForecast:
    id: str
    label: str
    capacity: int
    index: list[int]


@dataclass(frozen=True)
class Forecast:
    concourse: str
    bucket_minutes: int
    start: datetime
    zones: list[ZoneForecast]
    unassigned_flights: int
    unknown_aircraft_flights: int
    assumptions_version: str

    def zone(self, zone_id: str) -> ZoneForecast:
        for item in self.zones:
            if item.id == zone_id:
                return item
        raise KeyError(zone_id)

    def index_at(self, zone_id: str, when: datetime) -> int:
        series = self.zone(zone_id).index
        if not series:
            return 0
        when = require_aware(when, "when")
        elapsed = (when - self.start).total_seconds() / 60
        bucket = int(elapsed // self.bucket_minutes)
        return series[min(max(bucket, 0), len(series) - 1)]

    def to_public(self, data_source: dict) -> dict:
        return {
            "concourse": self.concourse,
            "bucket_minutes": self.bucket_minutes,
            "start": iso_z(self.start),
            "zones": [
                {"id": zone.id, "label": zone.label, "capacity": zone.capacity, "index": zone.index}
                for zone in self.zones
            ],
            "unassigned_flights": self.unassigned_flights,
            "unknown_aircraft_flights": self.unknown_aircraft_flights,
            "assumptions_version": self.assumptions_version,
            "data_source": data_source,
        }


def forecast(
    flights: list[Flight],
    graph: Graph,
    assumptions: Assumptions,
    start: datetime,
    hours: float,
    zone_multipliers: dict[str, float] | None = None,
    seat_scale: float = 1.0,
) -> Forecast:
    start = require_aware(start, "start")
    buckets = _bucket_count(hours)
    multipliers = zone_multipliers or {}
    people = {zone.id: [0.0] * buckets for zone in graph.zones.values()}
    unassigned = 0
    unknown = 0
    masses = _arrival_masses(assumptions)
    service = next((zone.id for zone in graph.zones.values() if zone.kind == "service"), None)

    for flight in flights:
        action = _scope(flight, graph)
        if action == "ignore":
            continue
        pax, used_default = _passengers(flight, assumptions, seat_scale)
        if used_default:
            unknown += 1
        if action == "unassigned":
            unassigned += 1
            continue
        if action == "cancel":
            if service is not None:
                begin = require_aware(flight.scheduled_out, "scheduled_out")
                _add(
                    people,
                    start,
                    service,
                    begin,
                    begin + timedelta(minutes=assumptions.cancellation_dwell_min),
                    pax * assumptions.cancellation_pax_fraction,
                )
            continue
        _add_flight(people, start, flight, graph, assumptions, pax, masses)

    zones = [
        ZoneForecast(
            zone.id,
            zone.label,
            zone.capacity,
            [_index(people[zone.id][i], zone.capacity, multipliers.get(zone.id, 1.0)) for i in range(buckets)],
        )
        for zone in graph.zones.values()
    ]
    return Forecast(
        concourse=graph.concourse,
        bucket_minutes=BUCKET_MINUTES,
        start=start,
        zones=zones,
        unassigned_flights=unassigned,
        unknown_aircraft_flights=unknown,
        assumptions_version=assumptions.version,
    )


def _bucket_count(hours: float) -> int:
    if hours <= 0:
        raise ValueError("hours must be positive")
    count = hours * 60 / BUCKET_MINUTES
    if abs(count - round(count)) > 1e-6:
        raise ValueError("hours must cover a whole number of 5-minute buckets")
    return int(round(count))


def _passengers(flight: Flight, assumptions: Assumptions, seat_scale: float) -> tuple[float, bool]:
    seats, used_default = seats_for(flight.aircraft_type)
    if used_default:
        seats = assumptions.default_seats
    return seats * seat_scale * assumptions.load_factor, used_default


def _scope(flight: Flight, graph: Graph) -> str:
    """place, cancel, unassigned, or ignore (another concourse)."""
    zone = graph.zone_for_gate(flight.gate) if flight.gate else None
    if flight.cancelled:
        if zone is not None:
            return "cancel"
        if not flight.gate or flight.concourse in (None, graph.concourse):
            return "unassigned"
        return "ignore"
    if zone is not None:
        return "place"
    if not flight.gate or flight.concourse in (None, graph.concourse):
        return "unassigned"
    return "ignore"


def _add_flight(
    people: dict[str, list[float]],
    start: datetime,
    flight: Flight,
    graph: Graph,
    assumptions: Assumptions,
    pax: float,
    masses: list[tuple[int, float]],
) -> None:
    zone = graph.zone_for_gate(flight.gate)
    if zone is None:
        return
    dep = _effective_departure(flight)
    close = assumptions.boarding_closes_min_before_dep
    weights = _amenity_weights(graph, zone.id, assumptions)
    weight_total = sum(weights.values())
    for minutes_before, mass in masses:
        count = pax * mass
        if count <= 0:
            continue
        arrive = dep - timedelta(minutes=minutes_before)
        leave = dep - timedelta(minutes=close)
        if leave <= arrive:
            continue
        visiting = count * assumptions.amenity_share
        _add(people, start, zone.id, arrive, leave, count - visiting)
        visit_min = min(assumptions.amenity_dwell_min, minutes_before - close)
        if visiting <= 0 or visit_min <= 0 or weight_total <= 0:
            _add(people, start, zone.id, arrive, leave, visiting)
            continue
        visit_end = arrive + timedelta(minutes=visit_min)
        for amenity_id, weight in weights.items():
            _add(people, start, amenity_id, arrive, visit_end, visiting * weight / weight_total)
        if visit_end < leave:
            _add(people, start, zone.id, visit_end, leave, visiting)


def _amenity_weights(graph: Graph, origin: str, assumptions: Assumptions) -> dict[str, float]:
    # Gravity model: closer, more attractive amenities draw more of the visiting passengers.
    weights: dict[str, float] = {}
    for zone in graph.zones.values():
        if zone.kind != "amenity":
            continue
        walk = graph.walk_seconds(origin, zone.id)
        if walk is None:
            continue
        weights[zone.id] = zone.attractiveness / (walk + assumptions.amenity_gravity_constant_s)
    return weights


def _effective_departure(flight: Flight) -> datetime:
    if flight.estimated_out is not None:
        return require_aware(flight.estimated_out, "estimated_out")
    scheduled = require_aware(flight.scheduled_out, "scheduled_out")
    return scheduled + timedelta(seconds=flight.delay_s or 0)


def _arrival_masses(assumptions: Assumptions) -> list[tuple[int, float]]:
    left = assumptions.boarding_closes_min_before_dep
    right = assumptions.arrive_min_before_dep
    mode = assumptions.arrival_peak_min_before_dep
    if not left < mode < right:
        mode = (left + right) // 2
    raw = [
        (minute, _tri_cdf(minute + 1, left, mode, right) - _tri_cdf(minute, left, mode, right))
        for minute in range(left, right)
    ]
    total = sum(mass for _, mass in raw) or 1.0
    return [(minute, mass / total) for minute, mass in raw]


def _tri_cdf(x: float, left: float, mode: float, right: float) -> float:
    if x <= left:
        return 0.0
    if x >= right:
        return 1.0
    if x <= mode:
        return (x - left) ** 2 / ((mode - left) * (right - left))
    return 1.0 - (right - x) ** 2 / ((right - mode) * (right - left))


def _add(
    people: dict[str, list[float]],
    start: datetime,
    zone_id: str,
    begin: datetime,
    end: datetime,
    count: float,
) -> None:
    series = people.get(zone_id)
    if series is None or count == 0 or end <= begin:
        return
    dt = BUCKET_MINUTES * 60
    lo = (begin - start).total_seconds() / dt
    hi = (end - start).total_seconds() / dt
    first = max(0, math.ceil(lo - 1e-9))
    last = min(len(series) - 1, math.floor(hi - 1e-9))
    for i in range(first, last + 1):
        series[i] += count


def _index(people: float, capacity: int, scale: float) -> int:
    if capacity <= 0:
        return 0
    return int(min(100, max(0, round(100 * people * scale / capacity))))


def with_assumptions(assumptions: Assumptions, **changes: object) -> Assumptions:
    return replace(assumptions, **changes)
