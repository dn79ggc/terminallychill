from datetime import datetime, timedelta, timezone

import pytest

from app.assumptions import Assumptions
from app.graph import Graph, Zone, load_graph
from app.model import Forecast, ZoneForecast, forecast
from app.providers.snapshot import SnapshotProvider
from app.ranking import INFEASIBLE_WARNING, rank

NOW = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)


def _flat_graph() -> Graph:
    zones = {
        "B-gates-1-10": Zone("B-gates-1-10", "Gates", "gates", 100, (1, 10)),
        "R1": Zone("R1", "Rest A", "rest", 10, near_zone="B-gates-1-10"),
        "R2": Zone("R2", "Rest B", "rest", 10, near_zone="B-gates-1-10"),
    }
    adj = {
        "B-gates-1-10": (("R1", 60), ("R2", 60)),
        "R1": (("B-gates-1-10", 60),),
        "R2": (("B-gates-1-10", 60),),
    }
    return Graph("B", 1, "web/concourse.svg", zones, tuple(adj), {}, adj, {})


def _flat_forecast() -> Forecast:
    return Forecast(
        "B",
        5,
        NOW,
        [ZoneForecast("B-gates-1-10", "Gates", 100, [20] * 36)],
        0,
        0,
        Assumptions().version,
    )


def test_leave_by_arithmetic_and_deterministic_tie_break():
    boarding = NOW + timedelta(hours=3)
    graph = _flat_graph()
    first = rank("b1", boarding, NOW, _flat_forecast(), graph, Assumptions(), limit=2)
    second = rank("B01", boarding, NOW, _flat_forecast(), graph, Assumptions(), limit=2)
    assert [spot.id for spot in first.spots] == ["R1", "R2"]
    assert [spot.id for spot in second.spots] == [spot.id for spot in first.spots]
    spot = first.spots[0]
    assert spot.walk_s_from_gate == 60
    assert spot.walk_s_back == 60
    assert spot.leave_by == boarding - timedelta(seconds=60) - timedelta(minutes=10)
    assert spot.route[0] == "B-gates-1-10" and spot.route[-1] == "R1"
    assert any("Lowest forecast crowd" in reason for reason in spot.reasons)


def test_boarding_too_soon_returns_no_spots():
    result = rank("B12", NOW + timedelta(minutes=8), NOW, _flat_forecast(), load_graph(), Assumptions())
    assert result.supported
    assert result.spots == []
    assert INFEASIBLE_WARNING in result.warnings


def test_gate_outside_the_concourse_is_not_guessed():
    result = rank("D9", NOW + timedelta(hours=2), NOW, _flat_forecast(), load_graph(), Assumptions())
    assert result.supported is False
    assert result.spots == []
    assert result.concourse == "D"


def test_unknown_gate_and_past_boarding_are_errors():
    graph = load_graph()
    with pytest.raises(ValueError, match="B1-B39"):
        rank("B99", NOW + timedelta(hours=2), NOW, _flat_forecast(), graph, Assumptions())
    with pytest.raises(ValueError, match="past"):
        rank("B12", NOW - timedelta(minutes=1), NOW, _flat_forecast(), graph, Assumptions())


def test_sample_ranking_prefers_a_feasible_spot():
    provider = SnapshotProvider(now=lambda: NOW)
    flights = [flight for page in provider.pages(NOW, NOW, 1) for flight in provider.parse(page)]
    built = forecast(flights, load_graph(), Assumptions(), NOW, 3)
    result = rank("B12", NOW + timedelta(hours=3), NOW, built, load_graph(), Assumptions())
    assert result.supported
    assert result.spots
    assert result.spots[0].stay_minutes >= 10
    assert result.spots[0].score >= result.spots[-1].score
