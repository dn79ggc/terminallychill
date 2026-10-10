from datetime import datetime, timezone

import httpx
import pytest

from app.providers.aeroapi import AeroAPIProvider
from app.providers.aviationstack import AviationstackProvider
from app.providers.base import ProviderError

KEY = "SUPER-SECRET-KEY"
START = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- AeroAPI
AERO_PAGE_1 = {
    "scheduled_departures": [
        {"ident_iata": "DL100", "fa_flight_id": "DAL100-1", "operator_iata": "DL", "gate_origin": "B22",
         "terminal_origin": "S", "aircraft_type": "B739 ", "scheduled_out": "2026-10-10T18:00:00Z",
         "estimated_out": "2026-10-10T18:05:00Z", "departure_delay": 300, "cancelled": False},
        {"ident_iata": "DL200", "gate_origin": None, "terminal_origin": "N", "aircraft_type": "A321",
         "scheduled_out": "2026-10-10T18:30:00Z", "estimated_out": None, "departure_delay": 0, "cancelled": False},
        {"ident_iata": None, "scheduled_out": "2026-10-10T18:30:00Z"},      # skipped: no ident
        {"ident_iata": "DL300", "scheduled_out": None},                      # skipped: no time
    ],
    "links": {"next": "/airports/KATL/flights/scheduled_departures?cursor=abc"},
    "num_pages": 2,
}
AERO_PAGE_2 = {"scheduled_departures": [], "links": None, "num_pages": 2}


def test_aeroapi_pages_follow_next_and_send_key_in_header():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        assert req.headers["x-apikey"] == KEY
        assert KEY not in str(req.url)
        return httpx.Response(200, json=AERO_PAGE_1 if "cursor" not in str(req.url) else AERO_PAGE_2)

    sleeps = []
    p = AeroAPIProvider(KEY, client=_client(handler), sleep=sleeps.append)
    pages = list(p.pages(START, END, max_pages=5))
    assert len(pages) == 2 and len(seen) == 2
    assert seen[0].url.params["start"] == "2026-10-10T18:00:00Z"
    assert "cursor=abc" in str(seen[1].url)
    assert sleeps == [6.5]            # rate-limit spacing between pages
    assert p.more_available is False


def test_aeroapi_page_cap_sets_more_available():
    p = AeroAPIProvider(KEY, client=_client(lambda r: httpx.Response(200, json=AERO_PAGE_1)), sleep=lambda s: None)
    assert len(list(p.pages(START, END, max_pages=1))) == 1
    assert p.more_available is True


def test_aeroapi_parse():
    p = AeroAPIProvider(KEY, client=_client(lambda r: httpx.Response(200)))
    flights = p.parse(AERO_PAGE_1)
    assert [f.ident for f in flights] == ["DL100", "DL200"]
    a, b = flights
    assert (a.uid, a.gate, a.concourse, a.terminal, a.aircraft_type, a.delay_s) == ("DAL100-1", "B22", "B", "S", "B739", 300)
    assert a.estimated_out.minute == 5 and a.scheduled_out.tzinfo is not None
    assert (b.gate, b.concourse, b.estimated_out) == (None, None, None)
    assert b.uid.startswith("aeroapi:DL200:")


def test_aeroapi_http_error_does_not_leak_key():
    p = AeroAPIProvider(KEY, client=_client(lambda r: httpx.Response(401, text=f"bad key {KEY}")))
    with pytest.raises(ProviderError) as ei:
        list(p.pages(START, END, 1))
    assert KEY not in str(ei.value) and "401" in str(ei.value)


def test_aeroapi_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "2"}) if calls["n"] == 1 else httpx.Response(200, json=AERO_PAGE_2)

    sleeps = []
    p = AeroAPIProvider(KEY, client=_client(handler), sleep=sleeps.append)
    assert len(list(p.pages(START, END, 1))) == 1 and sleeps == [2.0]


def test_aeroapi_requires_key():
    with pytest.raises(ProviderError):
        AeroAPIProvider("")


# ---------------------------------------------------------------- Aviationstack
def _avs_row(iata, gate, codeshared=False, status="scheduled"):
    return {
        "flight_status": status,
        "departure": {"iata": "ATL", "gate": gate, "terminal": "S", "delay": 10 if gate else None,
                      "scheduled": "2026-10-10T17:06:00+00:00", "estimated": "2026-10-10T17:16:00+00:00"},
        "airline": {"iata": iata[:2]},
        "flight": {"iata": iata, "codeshared": {"airline_iata": "dl"} if codeshared else None},
        "aircraft": None,
    }


def test_aviationstack_offset_paging_dedup_and_redaction():
    urls = []

    def handler(req: httpx.Request):
        urls.append(req.url)
        off = int(req.url.params["offset"])
        rows = [_avs_row("DL1", "B1"), _avs_row("AF1", "B1", codeshared=True)] if off == 0 else [_avs_row("DL2", None, status="cancelled")]
        return httpx.Response(200, json={"pagination": {"offset": off, "limit": 100, "count": len(rows), "total": 3}, "data": rows})

    p = AviationstackProvider(KEY, client=_client(handler))
    pages = list(p.pages(START, END, max_pages=5))
    assert len(pages) == 2
    assert [int(u.params["offset"]) for u in urls] == [0, 2]
    flights = [f for pg in pages for f in p.parse(pg)]
    assert [f.ident for f in flights] == ["DL1", "DL2"]           # codeshare AF1 dropped
    assert flights[0].delay_s == 600 and flights[0].concourse == "B"
    assert flights[1].cancelled is True and flights[1].gate is None


def test_aviationstack_api_error_and_network_error_do_not_leak_key():
    err = {"error": {"code": "usage_limit_reached", "message": f"limit hit {KEY}"}}
    p = AviationstackProvider(KEY, client=_client(lambda r: httpx.Response(200, json=err)))
    with pytest.raises(ProviderError) as ei:
        list(p.pages(START, END, 1))
    assert KEY not in str(ei.value) and "usage_limit_reached" in str(ei.value)

    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")        # httpx puts the full URL (with key) in errors

    p2 = AviationstackProvider(KEY, client=_client(boom))
    with pytest.raises(ProviderError) as ei2:
        list(p2.pages(START, END, 1))
    assert KEY not in str(ei2.value)


def test_aviationstack_page_cap():
    def handler(req):
        return httpx.Response(200, json={"pagination": {"count": 1, "total": 999}, "data": [_avs_row("DL1", "A1")]})

    p = AviationstackProvider(KEY, client=_client(handler))
    assert len(list(p.pages(START, END, max_pages=2))) == 2 and p.more_available is True
