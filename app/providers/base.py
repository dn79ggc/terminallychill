from __future__ import annotations

from datetime import datetime
from typing import Iterator, Protocol

from app.models import Flight


class ProviderError(RuntimeError):
    """Raised for any provider failure. Messages must never contain API keys."""


def redact(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


class FlightProvider(Protocol):
    name: str
    cache_raw: bool          # True = ingest saves raw pages to data/raw before parsing
    more_available: bool     # True if the page cap stopped the pull early

    def pages(self, start: datetime, end: datetime, max_pages: int) -> Iterator[dict]:
        """Yield raw response pages (dicts), at most max_pages."""

    def parse(self, page: dict) -> list[Flight]:
        """Turn one raw page into normalized Flight rows."""
