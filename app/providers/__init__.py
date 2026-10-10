from __future__ import annotations

from app.config import AIRPORT_IATA, AIRPORT_ICAO, Settings
from app.providers.aeroapi import AeroAPIProvider
from app.providers.aviationstack import AviationstackProvider
from app.providers.base import FlightProvider, ProviderError
from app.providers.snapshot import SnapshotProvider

PROVIDERS = ("aeroapi", "aviationstack", "snapshot")


def get_provider(name: str, settings: Settings, **kwargs) -> FlightProvider:
    """Exactly one provider per run. Data from different providers is never merged."""
    if name == "aeroapi":
        return AeroAPIProvider(settings.aeroapi_key or "", airport=AIRPORT_ICAO, **kwargs)
    if name == "aviationstack":
        return AviationstackProvider(settings.aviationstack_key or "", airport=AIRPORT_IATA, **kwargs)
    if name == "snapshot":
        return SnapshotProvider(**kwargs)
    raise ProviderError(f"Unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}")


def max_pages_for(name: str, settings: Settings) -> int:
    return {"aeroapi": settings.aeroapi_max_pages, "aviationstack": settings.aviationstack_max_pages}.get(name, 1)
