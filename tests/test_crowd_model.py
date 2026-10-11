import time
from datetime import datetime, timedelta, timezone

from app.assumptions import Assumptions
from app.graph import load_graph
from app.model import forecast, with_assumptions
from app.models import Flight
from app.providers.snapshot import SnapshotProvider

NOW = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)
GRAPH = load_graph()


def _flight(**overrides) -> Flight:
    dep = NOW + timedelta(hours=2)
    values = dict(
        uid="test:1",
        ident="ZZ1",
        operator="ZZ",
        gate="B5",
        concourse="B",
        terminal="S",
        aircraft_type="B739",
        scheduled_out=dep,
        estimated_out=dep,
        delay_s=0,
        cancelled=False,
        source="snapshot",
    )
    values.update(overrides)
    return Flight(**values)


def _quiet() -> Assumptions:
    return with_assumptions(Assumptions(), amenity_share=0)


def test_index_rises_before_departure_and_idle_zones_stay_empty():
    assumptions = _quiet()
    dep = NOW + timedelta(hours=2)
    result = forecast([_flight()], GRAPH, assumptions, NOW, 3)
    series = result.zone("B-gates-1-10").index
    at_60 = result.index_at("B-gates-1-10", dep - timedelta(minutes=60))
    at_30 = result.index_at("B-gates-1-10", dep - timedelta(minutes=30))
    assert at_30 > at_60 > 0
    assert max(result.zone("B-gates-31-39").index) == 0
    assert max(result.zone("B-rest-west").index) == 0
    assert all(0 <= value <= 100 for zone in result.zones for value in zone.index)
    assert len(series) == 36


def test_unknown_unassigned_and_cancellation_are_counted_not_spread():
    dep = NOW + timedelta(minutes=40)
    cancelled = _flight(uid="c", cancelled=True, scheduled_out=dep, estimated_out=dep)
    unknown = _flight(uid="u", gate="B15", concourse="B", aircraft_type="NOPE")
    unassigned = _flight(uid="n", gate=None, concourse=None, aircraft_type="B738")
    other = _flight(uid="a", gate="A4", concourse="A", aircraft_type="B738")
    result = forecast([cancelled, unknown, unassigned, other], GRAPH, _quiet(), NOW, 3)
    assert result.unknown_aircraft_flights == 1
    assert result.unassigned_flights == 1
    assert max(result.zone("B-gates-1-10").index) == 0
    assert max(result.zone("B-service").index) > 0


def test_delay_moves_the_curve_later_and_multiplier_is_a_hook():
    scheduled = NOW + timedelta(hours=2)
    early = forecast(
        [_flight(estimated_out=None, delay_s=0, scheduled_out=scheduled)],
        GRAPH,
        _quiet(),
        NOW,
        3,
    )
    late = forecast(
        [_flight(estimated_out=None, delay_s=20 * 60, scheduled_out=scheduled)],
        GRAPH,
        _quiet(),
        NOW,
        3,
    )
    moment = scheduled - timedelta(minutes=30)
    assert late.index_at("B-gates-1-10", moment) < early.index_at("B-gates-1-10", moment)
    scaled = forecast(
        [_flight()],
        GRAPH,
        _quiet(),
        NOW,
        3,
        zone_multipliers={"B-gates-1-10": 2.0},
    )
    base = early.index_at("B-gates-1-10", moment)
    assert base < scaled.index_at("B-gates-1-10", moment) <= 100


def test_naive_start_is_rejected():
    try:
        forecast([_flight()], GRAPH, _quiet(), datetime(2026, 10, 10, 18, 0), 3)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive datetime should be rejected")


def test_synthetic_sample_forecast_is_bounded_and_fast():
    provider = SnapshotProvider(now=lambda: NOW)
    flights = [flight for page in provider.pages(NOW, NOW, 1) for flight in provider.parse(page)]
    started = time.perf_counter()
    result = forecast(flights, GRAPH, Assumptions(), NOW, 3)
    assert time.perf_counter() - started < 1
    assert len(result.zones[0].index) == 3 * 60 // 5
    assert result.unknown_aircraft_flights == 0
    assert result.unassigned_flights > 0
    assert all(0 <= value <= 100 for zone in result.zones for value in zone.index)
    series = result.zone("B-gates-1-10").index
    assert any(series[i + 6] > series[i] for i in range(len(series) - 6))
    assert max(result.zone("B-rest-east-2").index) == 0
