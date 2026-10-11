from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.snapshot import SnapshotProvider
from app.repo import FlightLoad
from app.routes.deps import get_flight_loader


@pytest.fixture
def client():
    def loader(start: datetime, end: datetime) -> FlightLoad:
        provider = SnapshotProvider(now=lambda: start)
        flights = [flight for page in provider.pages(start, end, 1) for flight in provider.parse(page)]
        return FlightLoad(flights, "snapshot", start)

    app.dependency_overrides[get_flight_loader] = lambda: loader
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_graph_assumptions_and_forecast_shapes(client):
    graph = client.get("/api/graph")
    assert graph.status_code == 200
    assert graph.json()["concourse"] == "B"
    assert graph.json()["edges"]

    assumptions = client.get("/api/assumptions")
    assert assumptions.status_code == 200
    assert assumptions.json()["version"] == "2026-10-10.1"
    assert any(item["key"] == "load_factor" for item in assumptions.json()["parameters"])

    forecast = client.get(
        "/api/forecast",
        params={"concourse": "B", "start": "2026-10-10T18:00:00Z", "hours": 3},
    )
    assert forecast.status_code == 200
    body = forecast.json()
    assert body["bucket_minutes"] == 5
    assert len(body["zones"]) >= 8
    assert len(body["zones"][0]["index"]) == 36
    assert body["data_source"] == {
        "provider": "snapshot",
        "pulled_at": "2026-10-10T18:00:00Z",
        "synthetic": True,
    }
    assert "ZZ" not in forecast.text
    assert client.get("/api/forecast", params={"concourse": "A", "start": "2026-10-10T18:00:00Z", "hours": 3}).status_code == 422


def test_recommend_shapes(client):
    boarding = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = client.get("/api/recommend", params={"gate": "b12", "boarding": boarding, "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["gate"] == "B12"
    assert body["concourse"] == "B"
    assert body["data_source"]["synthetic"] is True
    assert 1 <= len(body["spots"]) <= 3
    spot = body["spots"][0]
    assert {"leave_by", "walk_s_from_gate", "route", "score", "reasons"} <= set(spot)
    assert "guarantee" not in response.text.lower()

    unsupported = client.get("/api/recommend", params={"gate": "D9", "boarding": boarding})
    assert unsupported.status_code == 200
    assert unsupported.json()["supported"] is False
    assert unsupported.json()["spots"] == []

    unknown = client.get("/api/recommend", params={"gate": "B99", "boarding": boarding})
    assert unknown.status_code == 422
    assert "B1-B39" in unknown.json()["detail"]

    soon = (datetime.now(timezone.utc) + timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    infeasible = client.get("/api/recommend", params={"gate": "B12", "boarding": soon})
    assert infeasible.status_code == 200
    assert infeasible.json()["spots"] == []
    assert infeasible.json()["warnings"]

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert client.get("/api/recommend", params={"gate": "B12", "boarding": past}).status_code == 422


def test_forecast_503_hides_the_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app.dependency_overrides.clear()
    client = TestClient(app)
    response = client.get(
        "/api/forecast",
        params={"concourse": "B", "start": "2026-10-10T18:00:00Z", "hours": 3},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert "DATABASE_URL" not in response.text
