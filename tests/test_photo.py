from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.counts import latest_counts, reset_counts
from app.main import app
from app.providers.snapshot import SnapshotProvider
from app.repo import FlightLoad
from app.routes.deps import get_flight_loader
from app.vision import count_people


def _png() -> bytes:
    image = np.zeros((24, 32, 3), dtype=np.uint8)
    image[:, :] = (30, 40, 50)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


class _Net:
    def __init__(self, detections):
        self.detections = detections

    def setInput(self, blob):
        assert blob.shape[0] == 1

    def forward(self):
        return self.detections


def _detection(class_id, confidence):
    box = np.zeros((1, 1, 1, 7), dtype=np.float32)
    box[0, 0, 0] = (0, class_id, confidence, 0.1, 0.1, 0.4, 0.5)
    return box


def test_synthetic_image_counts_person_boxes_and_ignores_other_classes():
    people = _detection(15, 0.91)
    chair = _detection(9, 0.99)
    weak = _detection(15, 0.2)
    stacked = np.concatenate([people, chair, weak], axis=2)
    image = cv2.imdecode(np.frombuffer(_png(), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert count_people(image, _Net(stacked)) == 1
    assert count_people(image, _Net(np.zeros((1, 1, 0, 7), dtype=np.float32))) == 0


@pytest.fixture
def client(monkeypatch):
    def loader(start: datetime, end: datetime) -> FlightLoad:
        provider = SnapshotProvider(now=lambda: start)
        flights = [flight for page in provider.pages(start, end, 1) for flight in provider.parse(page)]
        return FlightLoad(flights, "snapshot", start)

    monkeypatch.setattr("app.routes.photo.count_image_bytes", lambda data: 7)
    app.dependency_overrides[get_flight_loader] = lambda: loader
    reset_counts()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_counts()


def test_photo_adjusts_the_forecast_and_keeps_no_image(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = client.get(
        "/api/forecast",
        params={"concourse": "B", "start": "2026-10-10T18:00:00Z", "hours": 3},
    )
    assert before.status_code == 200
    response = client.post(
        "/api/photo",
        data={"zone_id": "B-gates-1-10"},
        files={"image": ("area.png", _png(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["zone_id"] == "B-gates-1-10"
    assert body["count"] == 7
    assert 0 <= body["adjusted_index"] <= 100
    assert "area.png" not in response.text
    stored = latest_counts(datetime.now(timezone.utc))
    assert len(stored) == 1 and stored[0].count == 7 and stored[0].zone_id == "B-gates-1-10"
    assert list(tmp_path.iterdir()) == []

    after = client.get(
        "/api/forecast",
        params={"concourse": "B", "start": "2026-10-10T18:00:00Z", "hours": 3},
    )
    prior = next(zone for zone in before.json()["zones"] if zone["id"] == "B-gates-1-10")
    corrected = next(zone for zone in after.json()["zones"] if zone["id"] == "B-gates-1-10")
    if max(prior["index"]) > 0:
        assert corrected["index"] != prior["index"]


def test_photo_rejects_a_non_image_an_unknown_zone_and_a_large_file(client):
    rejected = client.post(
        "/api/photo",
        data={"zone_id": "B-gates-1-10"},
        files={"image": ("notes.txt", b"hello", "text/plain")},
    )
    assert rejected.status_code == 415
    unknown = client.post(
        "/api/photo",
        data={"zone_id": "Z-nope"},
        files={"image": ("area.png", _png(), "image/png")},
    )
    assert unknown.status_code == 422
    too_big = client.post(
        "/api/photo",
        data={"zone_id": "B-gates-1-10"},
        files={"image": ("big.jpg", b"\xff" * (5 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert too_big.status_code == 413
    assert latest_counts(datetime.now(timezone.utc) + timedelta(seconds=1)) == []


def test_photo_rejects_a_small_file_with_a_huge_pixel_count(client):
    """A 100 Mpx PNG is well under 5 MB. It must be refused, not decoded."""
    ok, encoded = cv2.imencode(".png", np.zeros((10000, 10000, 3), dtype=np.uint8))
    assert ok and len(encoded) < 5 * 1024 * 1024
    response = client.post(
        "/api/photo",
        data={"zone_id": "B-gates-1-10"},
        files={"image": ("bomb.png", encoded.tobytes(), "image/png")},
    )
    assert response.status_code == 422
    assert latest_counts(datetime.now(timezone.utc) + timedelta(seconds=1)) == []
