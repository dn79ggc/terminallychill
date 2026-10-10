from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app.config import DISPLAY_TZ
from app.db import DatabaseUnavailable, connect, departures_by_concourse

log = logging.getLogger("airport-rest-finder")
app = FastAPI(title="Airport Rest Finder", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness plus a database check. Always returns 200 so the process stays 'up' for the proxy."""
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return {"ok": True, "db": True}
    except DatabaseUnavailable as e:
        log.warning("healthz: %s", e)
        return {"ok": True, "db": False}


@app.get("/api/summary")
def summary(hours: float = Query(2.0, gt=0, le=12)) -> dict:
    """Departures per concourse for the next `hours` hours (counts only; no flight-level data)."""
    now = datetime.now(timezone.utc)
    try:
        with connect() as conn:
            result = departures_by_concourse(conn, now, now + timedelta(hours=hours))
    except DatabaseUnavailable as e:
        log.warning("summary: %s", e)
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"as_of": now.isoformat(), "tz": DISPLAY_TZ, "hours": hours, **result}


# Static frontend (replace/extend in web/). Mounted last so the API routes above win.
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
