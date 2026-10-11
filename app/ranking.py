"""Rank rest spots by forecast crowd and walk time, and compute leave-by."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.assumptions import Assumptions
from app.graph import Graph, parse_gate
from app.model import Forecast
from app.timeutil import iso_z, require_aware

GATE_CHANGE_WARNING = "Gate assignments can change. Check the airport monitors."
INFEASIBLE_WARNING = "No quiet spot leaves enough time to wait and still make boarding."


@dataclass(frozen=True)
class Spot:
    id: str
    label: str
    zone_id: str
    walk_s_from_gate: int
    walk_s_back: int
    leave_by: datetime
    stay_minutes: int
    crowd_index_now: int
    crowd_index_peak: int
    route: list[str]
    score: float
    reasons: list[str]

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "zone_id": self.zone_id,
            "walk_s_from_gate": self.walk_s_from_gate,
            "walk_s_back": self.walk_s_back,
            "leave_by": iso_z(self.leave_by),
            "stay_minutes": self.stay_minutes,
            "crowd_index_now": self.crowd_index_now,
            "crowd_index_peak": self.crowd_index_peak,
            "route": self.route,
            "score": self.score,
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class Recommendation:
    gate: str
    concourse: str | None
    boarding: datetime
    supported: bool
    spots: list[Spot]
    warnings: list[str]
    assumptions_version: str

    def to_public(self, data_source: dict) -> dict:
        body = {
            "gate": self.gate,
            "concourse": self.concourse,
            "boarding": iso_z(self.boarding),
            "spots": [spot.to_public() for spot in self.spots],
            "warnings": self.warnings,
            "assumptions_version": self.assumptions_version,
            "data_source": data_source,
        }
        if not self.supported:
            body["supported"] = False
        return body


def rank(
    gate: str,
    boarding: datetime,
    now: datetime,
    forecast: Forecast,
    graph: Graph,
    assumptions: Assumptions,
    limit: int = 3,
) -> Recommendation:
    boarding = require_aware(boarding, "boarding")
    now = require_aware(now, "now")
    parsed = parse_gate(gate)
    label = f"{parsed[0]}{parsed[1]}" if parsed else (gate or "").strip().upper()
    if parsed is None:
        raise ValueError(f"Invalid gate. Supported gates are {graph.gate_label_span()}.")
    if parsed[0] != graph.concourse:
        return Recommendation(
            gate=label,
            concourse=parsed[0],
            boarding=boarding,
            supported=False,
            spots=[],
            warnings=[f"Only concourse {graph.concourse} is supported in this version."],
            assumptions_version=assumptions.version,
        )
    origin = graph.zone_for_gate(label)
    if origin is None:
        raise ValueError(f"Unknown gate {label}. Supported gates are {graph.gate_label_span()}.")
    if boarding <= now:
        raise ValueError("Boarding time is in the past.")

    feasible: list[tuple[float, float, str, Spot]] = []
    for rest in graph.zones.values():
        if rest.kind != "rest":
            continue
        walked = graph.shortest_path(origin.id, rest.id)
        if walked is None:
            continue
        walk_s, route = walked
        back = graph.shortest_path(rest.id, origin.id)
        walk_back = walk_s if back is None else back[0]
        t_arrive = now + timedelta(seconds=walk_s)
        leave_by = boarding - timedelta(seconds=walk_back) - timedelta(minutes=assumptions.leave_buffer_min)
        stay = leave_by - t_arrive
        if stay < timedelta(minutes=assumptions.min_stay_min):
            continue
        crowd_zone = rest.near_zone or rest.id
        samples = _samples(forecast, crowd_zone, t_arrive, leave_by)
        stay_crowd = _stay_crowd(samples, assumptions.stay_mean_weight)
        score = round(100 - stay_crowd - assumptions.walk_penalty_per_min * (walk_s / 60), 1)
        spot = Spot(
            id=rest.id,
            label=rest.label,
            zone_id=crowd_zone,
            walk_s_from_gate=walk_s,
            walk_s_back=walk_back,
            leave_by=leave_by,
            stay_minutes=int(stay.total_seconds() // 60),
            crowd_index_now=forecast.index_at(crowd_zone, now),
            crowd_index_peak=max(samples) if samples else 0,
            route=route,
            score=score,
            reasons=[],
        )
        feasible.append((score, stay_crowd, rest.id, spot))

    feasible.sort(key=lambda item: (-item[0], item[2]))
    quietest = min(feasible, key=lambda item: (item[1], item[2]))[2] if feasible else None
    chosen = [_with_reasons(item[3], quietest) for item in feasible[: max(limit, 0)]]
    warnings = [GATE_CHANGE_WARNING] if chosen else [INFEASIBLE_WARNING, GATE_CHANGE_WARNING]
    return Recommendation(
        gate=label,
        concourse=graph.concourse,
        boarding=boarding,
        supported=True,
        spots=chosen,
        warnings=warnings,
        assumptions_version=assumptions.version,
    )


def _samples(forecast: Forecast, zone_id: str, start: datetime, end: datetime) -> list[int]:
    series = forecast.zone(zone_id).index
    samples = [
        value
        for i, value in enumerate(series)
        if start <= forecast.start + timedelta(minutes=i * forecast.bucket_minutes) <= end
    ]
    return samples or [forecast.index_at(zone_id, start)]


def _stay_crowd(samples: list[int], mean_weight: float) -> float:
    mean = sum(samples) / len(samples)
    return mean_weight * mean + (1 - mean_weight) * max(samples)


def _with_reasons(spot: Spot, quietest_id: str | None) -> Spot:
    reasons: list[str] = []
    if spot.id == quietest_id:
        reasons.append("Lowest forecast crowd while you wait")
    elif spot.crowd_index_peak <= 33:
        reasons.append("Forecast crowd stays quiet while you wait")
    elif spot.crowd_index_peak <= 66:
        reasons.append("Forecast crowd stays moderate while you wait")
    else:
        reasons.append("Expected to be the busier end of the concourse")
    if spot.walk_s_from_gate < 30:
        reasons.append("Under 1 min walk from your gate")
    else:
        minutes = max(1, round(spot.walk_s_from_gate / 60))
        reasons.append(f"{minutes} min walk from your gate")
    return Spot(
        id=spot.id,
        label=spot.label,
        zone_id=spot.zone_id,
        walk_s_from_gate=spot.walk_s_from_gate,
        walk_s_back=spot.walk_s_back,
        leave_by=spot.leave_by,
        stay_minutes=spot.stay_minutes,
        crowd_index_now=spot.crowd_index_now,
        crowd_index_peak=spot.crowd_index_peak,
        route=spot.route,
        score=spot.score,
        reasons=reasons,
    )
