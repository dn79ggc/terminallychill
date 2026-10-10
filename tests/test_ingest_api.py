"""End to end against a real Postgres: snapshot provider -> ingest -> DB -> API."""
import os
import time
from datetime import datetime, timezone

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.ingest import prune_raw, run
from app.providers import get_provider
from app.providers.snapshot import SnapshotProvider


def test_snapshot_parse_is_relative_to_now():
    now = datetime(2026, 10, 10, 18, 0, 30, tzinfo=timezone.utc)
    p = SnapshotProvider(now=lambda: now)
    flights = [f for pg in p.pages(now, now, 1) for f in p.parse(pg)]
    assert len(flights) > 100 and all(f.source == "snapshot" for f in flights)
    assert all(f.ident.startswith("ZZ") for f in flights)             # clearly synthetic
    assert min(f.scheduled_out for f in flights) < now < max(f.scheduled_out for f in flights)


def test_ingest_is_idempotent_and_api_reports_counts(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    settings = get_settings()
    fixed = datetime.now(timezone.utc)
    provider = get_provider("snapshot", settings, now=lambda: fixed)   # pinned clock -> identical rows each run

    s1 = run(settings, provider, hours=3)
    assert s1["flights"] == s1["stored"] > 0 and s1["pages"] == 1
    run(settings, provider, hours=3)                                   # second run must upsert, not duplicate
    with psycopg.connect(db_url) as conn:
        (n,) = conn.execute("SELECT count(*) FROM flights").fetchone()
    assert n == s1["flights"]

    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    assert client.get("/healthz").json() == {"ok": True, "db": True}
    r = client.get("/api/summary", params={"hours": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["sources"] == ["snapshot"] and body["tz"] == "America/New_York"
    assert body["total"] == sum(c["departures"] for c in body["by_concourse"]) > 10
    assert [c["concourse"] for c in body["by_concourse"]] == list("TABCDEF") + ["?"]
    assert client.get("/api/summary", params={"hours": 0}).status_code == 422
    assert client.get("/").status_code == 200 and "ATL" in client.get("/").text


def test_dry_run_writes_nothing(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    settings = get_settings()
    stats = run(settings, get_provider("snapshot", settings), dry_run=True)
    assert stats["flights"] > 0 and stats["stored"] == 0
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM flights").fetchone()[0] == 0


def test_api_503_when_db_down_and_no_url_leak(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:hunter2@127.0.0.1:1/nope")
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    r = client.get("/api/summary")
    assert r.status_code == 503 and "hunter2" not in r.text
    h = client.get("/healthz")
    assert h.json() == {"ok": True, "db": False} and "hunter2" not in h.text


def test_prune_raw_removes_only_old_files(tmp_path):
    old, new = tmp_path / "aeroapi" / "old.json", tmp_path / "aeroapi" / "new.json"
    old.parent.mkdir()
    old.write_text("{}"); new.write_text("{}")
    forty_days_ago = time.time() - 40 * 86400
    os.utime(old, (forty_days_ago, forty_days_ago))
    assert prune_raw(tmp_path, 30) == 1 and not old.exists() and new.exists()


def test_ingest_saves_raw_page_before_parsing(tmp_path, monkeypatch):
    import json

    import httpx

    from app.providers.aeroapi import AeroAPIProvider

    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    page = {"scheduled_departures": [{"ident_iata": "DL1", "gate_origin": "C5", "aircraft_type": "B738",
                                      "scheduled_out": "2026-10-10T18:00:00Z"}], "links": None}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page)))
    stats = run(get_settings(), AeroAPIProvider("k", client=client), dry_run=True)
    files = list((tmp_path / "raw" / "aeroapi").glob("*_p01.json"))
    assert len(files) == 1 and json.loads(files[0].read_text()) == page
    assert stats["flights"] == 1 and stats["with_gate"] == 1 and stats["stored"] == 0


def test_purge_removes_only_that_source(db_url, tmp_path, monkeypatch, capsys):
    from app.ingest import main

    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    settings = get_settings()
    run(settings, get_provider("snapshot", settings))
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("""INSERT INTO flights (uid, ident, scheduled_out, source)
                        VALUES ('x1', 'DL1', now(), 'aeroapi')""")
    assert main(["--purge", "snapshot"]) == 0
    assert "purged" in capsys.readouterr().out
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT array_agg(DISTINCT source) FROM flights").fetchone()[0] == ["aeroapi"]
