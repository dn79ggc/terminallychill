"""Settings come from environment variables only (a local .env is loaded for convenience)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op if there is no .env (e.g. on the VM, where systemd injects the env)

AIRPORT_IATA = "ATL"
AIRPORT_ICAO = "KATL"
DISPLAY_TZ = "America/New_York"


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    flight_provider: str
    aeroapi_key: str | None
    aviationstack_key: str | None
    aeroapi_max_pages: int
    aviationstack_max_pages: int
    raw_dir: Path
    raw_retention_days: int
    person_model_dir: str
    gemini_api_key: str | None
    gemini_model: str


def get_settings() -> Settings:
    """Read the environment at call time (keeps tests simple)."""
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        flight_provider=(os.environ.get("FLIGHT_PROVIDER") or "aeroapi").strip().lower(),
        aeroapi_key=os.environ.get("AEROAPI_KEY") or None,
        aviationstack_key=os.environ.get("AVIATIONSTACK_KEY") or None,
        aeroapi_max_pages=int(os.environ.get("AEROAPI_MAX_PAGES") or 3),
        aviationstack_max_pages=int(os.environ.get("AVIATIONSTACK_MAX_PAGES") or 3),
        raw_dir=Path(os.environ.get("RAW_DIR") or "data/raw"),
        raw_retention_days=30,
        person_model_dir=(os.environ.get("PERSON_MODEL_DIR") or "").strip(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=(os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash").strip(),
    )
