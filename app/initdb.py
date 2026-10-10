"""Apply sql/*.sql to DATABASE_URL.  Usage: python -m app.initdb

001 (plain Postgres) must succeed. 002 (TimescaleDB) is skipped with a warning if the
extension is not available, so the same command works on a local Postgres.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from app.db import DatabaseUnavailable, connect

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def main() -> int:
    try:
        conn = connect()
    except DatabaseUnavailable as e:
        print(f"ERROR: {e}")
        return 1
    conn.autocommit = True
    for path in sorted(SQL_DIR.glob("*.sql")):
        try:
            conn.execute(path.read_text(encoding="utf-8"))
            print(f"applied  {path.name}")
        except psycopg.errors.UndefinedFunction:
            print(f"SKIPPED  {path.name}  (TimescaleDB not available on this database)")
        except psycopg.Error as e:
            print(f"ERROR    {path.name}: {type(e).__name__}: {str(e).splitlines()[0]}")
            return 1
    is_hyper = False
    if _has_timescale(conn):
        is_hyper = conn.execute(
            "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name = 'flights'"
        ).fetchone()[0] > 0
    print("hypertable:", "yes" if is_hyper else "no (plain table)")
    return 0


def _has_timescale(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'").fetchone() is not None


if __name__ == "__main__":
    sys.exit(main())
