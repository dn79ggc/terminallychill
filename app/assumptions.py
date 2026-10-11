"""Tunable forecast parameters and aircraft seat counts. One source of truth."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEATS_PATH = ROOT / "data" / "seats_by_type.json"

VERSION = "2026-10-10.1"


@dataclass(frozen=True)
class Assumptions:
    load_factor: float = 0.85
    arrive_min_before_dep: int = 90
    boarding_closes_min_before_dep: int = 10
    default_seats: int = 150
    amenity_share: float = 0.35
    amenity_dwell_min: int = 20
    leave_buffer_min: int = 10
    arrival_peak_min_before_dep: int = 40
    amenity_gravity_constant_s: int = 60
    cancellation_pax_fraction: float = 0.3
    cancellation_dwell_min: int = 60
    min_stay_min: int = 10
    walk_penalty_per_min: float = 3.0
    stay_mean_weight: float = 0.6
    version: str = VERSION

    def to_public(self) -> dict:
        return {
            "version": self.version,
            "parameters": [
                _param("load_factor", "Seats filled", self.load_factor, "fraction"),
                _param("arrive_min_before_dep", "Earliest arrival at gate", self.arrive_min_before_dep, "min"),
                _param(
                    "boarding_closes_min_before_dep",
                    "Leave gate area",
                    self.boarding_closes_min_before_dep,
                    "min",
                ),
                _param("default_seats", "Seats when aircraft unknown", self.default_seats, "seats"),
                _param("amenity_share", "Share visiting food/shops/restrooms", self.amenity_share, "fraction"),
                _param("amenity_dwell_min", "Time spent at amenities", self.amenity_dwell_min, "min"),
                _param("leave_buffer_min", "Safety buffer before boarding", self.leave_buffer_min, "min"),
                _param(
                    "arrival_peak_min_before_dep",
                    "Arrival curve peak",
                    self.arrival_peak_min_before_dep,
                    "min",
                    "Triangular curve. DEFAULT, not measured",
                ),
                _param(
                    "amenity_gravity_constant_s",
                    "Amenity walk constant",
                    self.amenity_gravity_constant_s,
                    "s",
                ),
                _param(
                    "cancellation_pax_fraction",
                    "Cancelled passengers at customer service",
                    self.cancellation_pax_fraction,
                    "fraction",
                ),
                _param(
                    "cancellation_dwell_min",
                    "Customer-service load after a cancellation",
                    self.cancellation_dwell_min,
                    "min",
                ),
                _param("min_stay_min", "Minimum useful wait", self.min_stay_min, "min"),
                _param("walk_penalty_per_min", "Score penalty per walking minute", self.walk_penalty_per_min, "points"),
                _param("stay_mean_weight", "Weight on average crowd during the wait", self.stay_mean_weight, "fraction"),
            ],
        }


def _param(key: str, label: str, value: float | int, unit: str, note: str = "DEFAULT, not measured") -> dict:
    return {"key": key, "label": label, "value": value, "unit": unit, "note": note}


_SEATS: dict | None = None


def seat_table() -> dict:
    global _SEATS
    if _SEATS is None:
        _SEATS = json.loads(SEATS_PATH.read_text(encoding="utf-8"))
    return _SEATS


def seats_for(aircraft_type: str | None, default: int | None = None) -> tuple[int, bool]:
    """Return (seats, used_default). Unknown and missing types use the default."""
    table = seat_table()
    fallback = table["_default"] if default is None else default
    if not aircraft_type:
        return fallback, True
    key = aircraft_type.strip().upper()
    if key in table and not key.startswith("_"):
        return int(table[key]), False
    return fallback, True


def get_assumptions() -> Assumptions:
    return Assumptions()
