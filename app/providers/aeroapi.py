"""FlightAware AeroAPI: GET /airports/{id}/flights/scheduled_departures.

Auth is the x-apikey header (the key never appears in a URL). Personal tier allows
10 result sets/minute, so pages are spaced out. One page = up to 15 flights.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Iterator

import httpx

from app.models import Flight, concourse_of, parse_dt
from app.providers.base import ProviderError, redact

BASE = "https://aeroapi.flightaware.com/aeroapi"
_FMT = "%Y-%m-%dT%H:%M:%SZ"


class AeroAPIProvider:
    name = "aeroapi"
    cache_raw = True

    def __init__(
        self,
        api_key: str,
        airport: str = "KATL",
        client: httpx.Client | None = None,
        base_url: str = BASE,
        min_interval_s: float = 6.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ProviderError("AEROAPI_KEY is not set")
        self._key = api_key
        self.airport = airport
        self._client = client or httpx.Client(timeout=30)
        self._base = base_url
        self._interval = min_interval_s
        self._sleep = sleep
        self.more_available = False

    # -- HTTP ---------------------------------------------------------------
    def _get(self, url: str, params: dict | None) -> dict:
        for attempt in range(3):
            try:
                resp = self._client.get(url, params=params, headers={"x-apikey": self._key})
            except httpx.HTTPError as e:
                raise ProviderError(redact(f"AeroAPI request failed: {e}", self._key)) from None
            if resp.status_code == 429 and attempt < 2:
                self._sleep(float(resp.headers.get("Retry-After") or 10))
                continue
            if resp.status_code != 200:
                hint = " (check AEROAPI_KEY)" if resp.status_code in (401, 403) else ""
                raise ProviderError(redact(f"AeroAPI HTTP {resp.status_code}{hint}: {resp.text[:200]}", self._key))
            return resp.json()
        raise ProviderError("AeroAPI rate limit: gave up after retries")

    def pages(self, start: datetime, end: datetime, max_pages: int) -> Iterator[dict]:
        self.more_available = False
        url = f"{self._base}/airports/{self.airport}/flights/scheduled_departures"
        params: dict | None = {"start": start.strftime(_FMT), "end": end.strftime(_FMT)}
        for n in range(max_pages):
            body = self._get(url, params)
            yield body
            nxt = (body.get("links") or {}).get("next")
            if not nxt:
                return
            if n == max_pages - 1:
                self.more_available = True
                return
            url, params = self._base + nxt, None   # next link already carries all parameters
            self._sleep(self._interval)

    # -- Parsing ------------------------------------------------------------
    def parse(self, page: dict) -> list[Flight]:
        out: list[Flight] = []
        for fl in page.get("scheduled_departures") or []:
            sched = parse_dt(fl.get("scheduled_out"))
            ident = fl.get("ident_iata") or fl.get("ident")
            if sched is None or not ident:
                continue
            gate = (fl.get("gate_origin") or "").strip() or None
            out.append(
                Flight(
                    uid=fl.get("fa_flight_id") or f"aeroapi:{ident}:{sched.isoformat()}",
                    ident=ident,
                    operator=fl.get("operator_iata") or fl.get("operator"),
                    gate=gate,
                    concourse=concourse_of(gate),
                    terminal=fl.get("terminal_origin"),
                    aircraft_type=(fl.get("aircraft_type") or "").strip() or None,
                    scheduled_out=sched,
                    estimated_out=parse_dt(fl.get("estimated_out")),
                    delay_s=fl.get("departure_delay"),
                    cancelled=bool(fl.get("cancelled")),
                    source=self.name,
                )
            )
        return out
