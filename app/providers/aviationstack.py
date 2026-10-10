"""Aviationstack: GET /v1/flights?dep_iata=ATL (offset pagination, 100 per page max on free).

The key travels in the query string, so every error message is redacted before it
leaves this module. Codeshare rows (flight.codeshared) are dropped: they duplicate the
operating flight. No aircraft type is available on this provider (aircraft.* is null).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

import httpx

from app.models import Flight, concourse_of, parse_dt
from app.providers.base import ProviderError, redact

BASE = "https://api.aviationstack.com/v1/flights"


class AviationstackProvider:
    name = "aviationstack"
    cache_raw = True

    def __init__(self, api_key: str, airport: str = "ATL", client: httpx.Client | None = None, base_url: str = BASE):
        if not api_key:
            raise ProviderError("AVIATIONSTACK_KEY is not set")
        self._key = api_key
        self.airport = airport
        self._client = client or httpx.Client(timeout=30)
        self._base = base_url
        self.more_available = False

    def pages(self, start: datetime, end: datetime, max_pages: int) -> Iterator[dict]:
        # Free plan cannot filter by time window; start/end are ignored here.
        self.more_available = False
        offset = 0
        for n in range(max_pages):
            params = {"access_key": self._key, "dep_iata": self.airport, "limit": 100, "offset": offset}
            try:
                resp = self._client.get(self._base, params=params)
                body = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                raise ProviderError(redact(f"Aviationstack request failed: {e}", self._key)) from None
            if "error" in body:
                err = body["error"] or {}
                raise ProviderError(redact(f"Aviationstack error {err.get('code')}: {err.get('message')}", self._key))
            yield body
            pg = body.get("pagination") or {}
            count, total = pg.get("count") or 0, pg.get("total") or 0
            offset += count
            if count == 0 or offset >= total:
                return
            if n == max_pages - 1:
                self.more_available = True

    def parse(self, page: dict) -> list[Flight]:
        out: list[Flight] = []
        for row in page.get("data") or []:
            fl, dep = row.get("flight") or {}, row.get("departure") or {}
            if fl.get("codeshared"):
                continue
            ident = fl.get("iata")
            sched = parse_dt(dep.get("scheduled"))
            if not ident or sched is None:
                continue
            gate = (dep.get("gate") or "").strip() or None
            delay_min = dep.get("delay")          # minutes (unit not yet verified against docs)
            out.append(
                Flight(
                    uid=f"aviationstack:{ident}:{sched.isoformat()}",
                    ident=ident,
                    operator=(row.get("airline") or {}).get("iata"),
                    gate=gate,
                    concourse=concourse_of(gate),
                    terminal=dep.get("terminal"),
                    aircraft_type=None,
                    scheduled_out=sched,
                    estimated_out=parse_dt(dep.get("estimated")),
                    delay_s=int(delay_min) * 60 if delay_min is not None else None,
                    cancelled=row.get("flight_status") == "cancelled",
                    source=self.name,
                )
            )
        return out
