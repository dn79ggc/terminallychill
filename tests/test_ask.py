import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.nl import AskUnavailable, explanation, validate_parameters
from app.providers.snapshot import SnapshotProvider
from app.ranking import Recommendation
from app.repo import FlightLoad
from app.routes.deps import get_flight_loader

NOW = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)

SENTENCES = {
    "nap near B12, 4 hours": {"gate": "B12", "hours": 4, "preferences": "quiet"},
    "somewhere quiet by b22 for 2 hours": {"gate": "b22", "hours": 2, "preferences": "quiet"},
    "I board at B5 in 90 minutes": {"gate": "B5", "hours": 1.5, "preferences": ""},
    "rest near B30, about 3 hours, away from food": {"gate": "B30", "hours": 3, "preferences": "away from food"},
    "gate B18, 1 hour": {"gate": "B18", "hours": 1, "preferences": ""},
}


def test_malformed_model_output_is_rejected():
    with pytest.raises(Exception):
        validate_parameters("not json")
    with pytest.raises(Exception):
        validate_parameters('{"gate": "B12"}')
    with pytest.raises(Exception):
        validate_parameters('{"gate": "B12", "hours": true}')
    with pytest.raises(Exception):
        validate_parameters('{"gate": "lounge", "hours": 2}')
    with pytest.raises(Exception):
        validate_parameters('{"gate": "B12", "hours": 0}')
    with pytest.raises(Exception):
        validate_parameters('{"gate": "B12", "hours": 20}')
    fenced = validate_parameters('```json\n{"gate": "b12", "hours": 2, "preferences": ""}\n```')
    assert fenced == {"gate": "B12", "hours": 2.0, "preferences": ""}


def test_explanation_uses_our_numbers_only():
    text = explanation(
        Recommendation(
            gate="B12",
            concourse="B",
            boarding=NOW,
            supported=False,
            spots=[],
            warnings=["Only concourse B is supported in this version."],
            assumptions_version="x",
        )
    )
    assert "Only concourse B" in text
    assert "accurate" not in text.lower()


@pytest.fixture
def client(monkeypatch):
    def loader(start: datetime, end: datetime) -> FlightLoad:
        provider = SnapshotProvider(now=lambda: start)
        flights = [flight for page in provider.pages(start, end, 1) for flight in provider.parse(page)]
        return FlightLoad(flights, "snapshot", start)

    def fake_post(sentence, settings: Settings):
        if sentence not in SENTENCES:
            raise AskUnavailable("down")
        return json.dumps(SENTENCES[sentence])

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.nl._post_gemini", fake_post)
    app.dependency_overrides[get_flight_loader] = lambda: loader
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_five_sentences_reuse_the_ranking(client):
    for sentence, expected in SENTENCES.items():
        response = client.post("/api/ask", json={"text": sentence})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["parameters"]["gate"] == expected["gate"].upper()
        assert body["parameters"]["hours"] == expected["hours"]
        assert body["recommendation"]["gate"] == expected["gate"].upper()
        assert "Crowd index" in body["explanation"]
        assert "guarantee" not in response.text.lower()
        assert "test-key" not in response.text


def test_ask_errors_stay_clear_when_gemini_is_missing_or_broken(client, monkeypatch):
    monkeypatch.setattr("app.nl._post_gemini", lambda sentence, settings: "nope")
    broken = client.post("/api/ask", json={"text": "nap near B12, 4 hours"})
    assert broken.status_code == 422
    assert "nope" not in broken.text

    def down(sentence, settings):
        raise AskUnavailable("down")

    monkeypatch.setattr("app.nl._post_gemini", down)
    down = client.post("/api/ask", json={"text": "nap near B12, 4 hours"})
    assert down.status_code == 503
    assert down.json()["detail"] == "Ask service is unavailable."

    monkeypatch.setenv("GEMINI_API_KEY", "")
    missing = client.post("/api/ask", json={"text": "nap near B12, 4 hours"})
    assert missing.status_code == 503
    assert missing.json()["detail"] == "Ask service is not configured."
