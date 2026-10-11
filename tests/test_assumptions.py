import json
from pathlib import Path

from app.assumptions import VERSION, Assumptions, seats_for

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "atl_synthetic.json"
SPEC_KEYS = {
    "load_factor",
    "arrive_min_before_dep",
    "boarding_closes_min_before_dep",
    "default_seats",
    "amenity_share",
    "amenity_dwell_min",
    "leave_buffer_min",
}


def test_public_assumptions_include_the_contract_defaults():
    body = Assumptions().to_public()
    assert body["version"] == VERSION
    keys = {item["key"] for item in body["parameters"]}
    assert SPEC_KEYS <= keys
    by_key = {item["key"]: item["value"] for item in body["parameters"]}
    assert by_key["load_factor"] == 0.85
    assert by_key["default_seats"] == 150
    assert all(item["note"] for item in body["parameters"])


def test_every_sample_aircraft_has_its_own_seat_count():
    flights = json.loads(SAMPLE.read_text(encoding="utf-8"))["flights"]
    types = {flight.get("aircraft_type") for flight in flights}
    assert types
    for aircraft in types:
        seats, used_default = seats_for(aircraft)
        assert not used_default
        assert seats != 150 or aircraft != "A320"


def test_unknown_aircraft_uses_the_default_and_is_countable():
    seats, used_default = seats_for("NOPE")
    assert used_default and seats == 150
    seats, used_default = seats_for(None)
    assert used_default and seats == 150
    seats, used_default = seats_for("B739")
    assert not used_default and seats == 180
