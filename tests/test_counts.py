from datetime import datetime, timedelta, timezone

from app.counts import decayed_multiplier, latest_counts, raw_multiplier, remember_count, reset_counts

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def test_multiplier_clamps_and_fades_to_one():
    assert raw_multiplier(10, 10) == 1
    assert raw_multiplier(100, 10) == 2
    assert raw_multiplier(1, 10) == 0.5
    assert raw_multiplier(4, 0) == 2
    assert raw_multiplier(0, 0) == 1
    assert decayed_multiplier(100, 10, timedelta(0)) == 2
    assert decayed_multiplier(100, 10, timedelta(minutes=15)) == 1.5
    assert decayed_multiplier(100, 10, timedelta(minutes=30)) == 1
    assert decayed_multiplier(1, 10, timedelta(minutes=15)) == 0.75


def test_counts_expire_after_thirty_minutes_and_keep_the_newest():
    reset_counts()
    remember_count(NOW - timedelta(minutes=31), "B-gates-1-10", 9)
    remember_count(NOW - timedelta(minutes=10), "B-gates-1-10", 3)
    remember_count(NOW - timedelta(minutes=5), "B-gates-1-10", 4)
    remember_count(NOW - timedelta(minutes=2), "B-food-1", 1)
    current = {record.zone_id: record.count for record in latest_counts(NOW)}
    assert current == {"B-gates-1-10": 4, "B-food-1": 1}
    assert latest_counts(NOW + timedelta(minutes=29)) == []


def test_a_fresh_photo_changes_only_that_zone():
    from app.assumptions import Assumptions
    from app.counts import forecast_with_corrections
    from app.graph import load_graph
    from app.model import forecast
    from app.models import Flight

    graph = load_graph()
    assumptions = Assumptions(amenity_share=0)
    dep = NOW + timedelta(hours=2)
    flight = Flight(
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
    prior = forecast([flight], graph, assumptions, NOW, 3)
    moment = dep - timedelta(minutes=30)
    assert prior.people_at("B-gates-1-10", moment) > 0
    remember_count(moment, "B-gates-1-10", 0)
    corrected = forecast_with_corrections([flight], graph, assumptions, NOW, 3, moment)
    assert corrected.index_at("B-gates-1-10", moment) < prior.index_at("B-gates-1-10", moment)
    assert corrected.index_at("B-gates-11-20", moment) == prior.index_at("B-gates-11-20", moment)

