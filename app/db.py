from __future__ import annotations

from datetime import datetime
from typing import Iterable

import psycopg

from app.config import get_settings
from app.models import CONCOURSES, Flight


class DatabaseUnavailable(RuntimeError):
    """DATABASE_URL missing or the database cannot be reached. Never includes the URL."""


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or get_settings().database_url
    if not url:
        raise DatabaseUnavailable("DATABASE_URL is not set")
    try:
        return psycopg.connect(url, connect_timeout=10)
    except psycopg.Error as e:
        raise DatabaseUnavailable(f"cannot connect to database ({type(e).__name__})") from None


_UPSERT = """
INSERT INTO flights (uid, ident, operator, gate, concourse, terminal, aircraft_type,
                     scheduled_out, estimated_out, delay_s, cancelled, source, fetched_at)
VALUES (%(uid)s, %(ident)s, %(operator)s, %(gate)s, %(concourse)s, %(terminal)s, %(aircraft_type)s,
        %(scheduled_out)s, %(estimated_out)s, %(delay_s)s, %(cancelled)s, %(source)s, now())
ON CONFLICT (uid, scheduled_out) DO UPDATE SET
    gate = EXCLUDED.gate, concourse = EXCLUDED.concourse, terminal = EXCLUDED.terminal,
    aircraft_type = COALESCE(EXCLUDED.aircraft_type, flights.aircraft_type),
    estimated_out = EXCLUDED.estimated_out, delay_s = EXCLUDED.delay_s,
    cancelled = EXCLUDED.cancelled, source = EXCLUDED.source, fetched_at = now()
"""


def upsert_flights(conn: psycopg.Connection, flights: Iterable[Flight]) -> int:
    rows = [f.__dict__ for f in flights]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT, rows)
    conn.commit()
    return len(rows)


def purge_source(conn: psycopg.Connection, source: str) -> int:
    """Delete all rows that came from one source (e.g. 'snapshot' before loading real data)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM flights WHERE source = %s", (source,))
        n = cur.rowcount
    conn.commit()
    return n


def departures_by_concourse(conn: psycopg.Connection, start: datetime, end: datetime) -> dict:
    """Non-cancelled departures whose effective time (estimated, else scheduled) is in [start, end)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(concourse, '?') AS c, count(*)
            FROM flights
            WHERE NOT cancelled AND coalesce(estimated_out, scheduled_out) >= %s
                  AND coalesce(estimated_out, scheduled_out) < %s
            GROUP BY 1
            """,
            (start, end),
        )
        counts = dict(cur.fetchall())
        cur.execute("SELECT max(fetched_at), array_agg(DISTINCT source) FROM flights")
        last_fetched, sources = cur.fetchone()
    order = list(CONCOURSES) + ["?"]
    return {
        "by_concourse": [{"concourse": c, "departures": counts.get(c, 0)} for c in order],
        "total": sum(counts.values()),
        "last_fetched_at": last_fetched.isoformat() if last_fetched else None,
        "sources": sources or [],
    }
