"""Read flights for the forecast. Kept out of app/db.py, which is Tier A."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from app.db import DatabaseUnavailable, connect
from app.models import Flight
from app.timeutil import iso_z, require_aware

# Passengers can be in the concourse 90 minutes before departure, and a departure
# just after the window still contributes. Cancellations are keyed off scheduled_out.
ARRIVAL_PAD = timedelta(minutes=90)

_SELECT = """
SELECT uid, ident, operator, gate, concourse, terminal, aircraft_type,
       scheduled_out, estimated_out, delay_s, cancelled, source, fetched_at
FROM flights
WHERE (
        coalesce(
            estimated_out,
            scheduled_out + (coalesce(delay_s, 0) * interval '1 second')
        ) >= %s
    AND coalesce(
            estimated_out,
            scheduled_out + (coalesce(delay_s, 0) * interval '1 second')
        ) < %s
) OR (
    cancelled AND scheduled_out >= %s AND scheduled_out < %s
)
"""


@dataclass(frozen=True)
class FlightLoad:
    flights: list[Flight]
    provider: str
    pulled_at: datetime

    def data_source(self) -> dict:
        return {
            "provider": self.provider,
            "pulled_at": iso_z(self.pulled_at),
            "synthetic": self.provider == "snapshot",
        }


def query_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start = require_aware(start, "start")
    end = require_aware(end, "end")
    return start - ARRIVAL_PAD, end + ARRIVAL_PAD


def load_flights(conn: psycopg.Connection, start: datetime, end: datetime) -> list[Flight]:
    return read_window(conn, start, end).flights


def load_window(start: datetime, end: datetime) -> FlightLoad:
    with connect() as conn:
        return read_window(conn, start, end)


def read_window(conn: psycopg.Connection, start: datetime, end: datetime) -> FlightLoad:
    begin, finish = query_bounds(start, end)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT, (begin, finish, begin, finish))
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise DatabaseUnavailable(f"query failed ({type(exc).__name__})") from None
    flights = [flight_from_row(row) for row in rows]
    if not rows:
        return FlightLoad(flights, "unknown", datetime.now(timezone.utc))
    newest = max(rows, key=lambda row: row["fetched_at"] or datetime.min.replace(tzinfo=timezone.utc))
    pulled = newest["fetched_at"] or datetime.now(timezone.utc)
    if pulled.tzinfo is None:
        pulled = pulled.replace(tzinfo=timezone.utc)
    return FlightLoad(flights, newest["source"] or "unknown", pulled)


def flight_from_row(row: dict) -> Flight:
    scheduled = _aware(row["scheduled_out"])
    estimated = _aware(row["estimated_out"]) if row["estimated_out"] else None
    return Flight(
        uid=row["uid"],
        ident=row["ident"],
        operator=row["operator"],
        gate=row["gate"],
        concourse=row["concourse"],
        terminal=row["terminal"],
        aircraft_type=row["aircraft_type"],
        scheduled_out=scheduled,
        estimated_out=estimated,
        delay_s=row["delay_s"],
        cancelled=bool(row["cancelled"]),
        source=row["source"],
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
