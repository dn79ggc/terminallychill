"""Show whether zone ranking stays put when the main assumptions move.

There is no ground-truth crowd count at ATL, so this cannot say the forecast is right.
It only shows whether the ordering is an artifact of one default.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.assumptions import Assumptions
from app.graph import load_graph
from app.model import Forecast, forecast, with_assumptions
from app.providers.snapshot import SnapshotProvider
from app.ranking import rank

NOW = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)


def build_report(now: datetime = NOW) -> str:
    graph = load_graph()
    assumptions = Assumptions()
    provider = SnapshotProvider(now=lambda: now)
    flights = [flight for page in provider.pages(now, now, 1) for flight in provider.parse(page)]
    baseline = forecast(flights, graph, assumptions, now, 3)
    base_order = _order(baseline)
    boarding = now + timedelta(hours=3)
    base_spot = _top_spot(flights, graph, assumptions, now, boarding)

    variations = [
        ("Load factor 0.70", with_assumptions(assumptions, load_factor=0.70), 1.0),
        ("Load factor 0.95", with_assumptions(assumptions, load_factor=0.95), 1.0),
        ("Seats -20%", assumptions, 0.8),
        ("Seats +20%", assumptions, 1.2),
        ("Arrival peak 25 min before departure", with_assumptions(assumptions, arrival_peak_min_before_dep=25), 1.0),
        ("Arrival peak 70 min before departure", with_assumptions(assumptions, arrival_peak_min_before_dep=70), 1.0),
    ]
    lines = [
        "# Assumption sensitivity",
        "",
        "Concourse B, synthetic sample, 3-hour forecast from "
        f"{now.strftime('%Y-%m-%d %H:%M')} UTC. Zones are ordered by peak crowd index.",
        "",
        "This cannot show that the forecast matches real crowds at ATL. "
        "There is no ground-truth crowd count to compare against. "
        "Walking times and zone capacities are hand estimates and were not varied.",
        "",
        "| Change | Top zone by peak index | Zones that changed rank | Top rest spot for gate B12 |",
        "|---|---|---|---|",
        f"| Baseline (load factor {assumptions.load_factor}) | {base_order[0]} | — | {base_spot} |",
    ]
    for label, varied, seat_scale in variations:
        result = forecast(flights, graph, varied, now, 3, seat_scale=seat_scale)
        order = _order(result)
        moved = sum(1 for zone, base in zip(order, base_order) if zone != base)
        spot = _top_spot(flights, graph, varied, now, boarding, seat_scale=seat_scale)
        lines.append(f"| {label} | {order[0]} | {moved} | {spot} |")
    lines.extend(
        [
            "",
            f"Baseline zone order: {', '.join(base_order)}.",
            "",
        ]
    )
    return "\n".join(lines)


def _order(result: Forecast) -> list[str]:
    return [zone.id for zone in sorted(result.zones, key=lambda zone: (-max(zone.index), zone.id))]


def _top_spot(flights, graph, assumptions, now, boarding, seat_scale: float = 1.0) -> str:
    built = forecast(flights, graph, assumptions, now, 3, seat_scale=seat_scale)
    result = rank("B12", boarding, now, built, graph, assumptions)
    if not result.spots:
        return "(none feasible)"
    return result.spots[0].id


if __name__ == "__main__":
    print(build_report())
