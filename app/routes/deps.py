"""Shared route helpers. The flight loader is a dependency so tests can skip the database."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException

from app.db import DatabaseUnavailable
from app.repo import FlightLoad, load_window

log = logging.getLogger("airport-rest-finder")

FlightLoader = Callable[[datetime, datetime], FlightLoad]


def get_flight_loader() -> FlightLoader:
    return load_window


def load_or_503(loader: FlightLoader, start: datetime, end: datetime) -> FlightLoad:
    try:
        return loader(start, end)
    except DatabaseUnavailable as exc:
        log.warning("flights: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from None
