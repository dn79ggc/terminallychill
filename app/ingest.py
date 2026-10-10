"""Pull departures from ONE provider, save raw pages, parse, upsert into the database.

Usage:
    python -m app.ingest                      # provider from FLIGHT_PROVIDER, next 3 hours
    python -m app.ingest --hours 2 --max-pages 2
    python -m app.ingest --dry-run            # fetch + parse only, no database writes
    python -m app.ingest --provider snapshot  # synthetic data, no key needed
    python -m app.ingest --purge snapshot     # delete all rows from one source, then exit
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.db import DatabaseUnavailable, connect, purge_source, upsert_flights
from app.models import Flight
from app.providers import get_provider, max_pages_for
from app.providers.base import FlightProvider, ProviderError


def prune_raw(raw_dir: Path, days: int, now: float | None = None) -> int:
    """Delete raw page files older than `days` (AeroAPI license: raw data max 30 days)."""
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    if raw_dir.exists():
        for p in raw_dir.rglob("*.json"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
    return removed


def run(
    settings: Settings,
    provider: FlightProvider,
    hours: float = 3.0,
    max_pages: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    max_pages = max_pages if max_pages is not None else max_pages_for(provider.name, settings)
    flights: list[Flight] = []
    pages = 0
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    for page in provider.pages(now, now + timedelta(hours=hours), max_pages):
        pages += 1
        if provider.cache_raw:                       # save raw BEFORE parsing, so a parser bug loses nothing
            d = settings.raw_dir / provider.name
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{stamp}_p{pages:02d}.json").write_text(json.dumps(page), encoding="utf-8")
        flights.extend(provider.parse(page))

    stored = 0
    if not dry_run and flights:
        conn = connect(settings.database_url)
        try:
            stored = upsert_flights(conn, flights)
        finally:
            conn.close()

    pruned = prune_raw(settings.raw_dir, settings.raw_retention_days) if provider.cache_raw else 0
    n = len(flights)
    with_gate = sum(1 for f in flights if f.gate)
    return {
        "provider": provider.name,
        "pages": pages,
        "flights": n,
        "with_gate": with_gate,
        "stored": stored,
        "more_available": provider.more_available,
        "raw_pruned": pruned,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="aeroapi | aviationstack | snapshot (default: $FLIGHT_PROVIDER)")
    ap.add_argument("--hours", type=float, default=3.0, help="window length from now (default 3)")
    ap.add_argument("--max-pages", type=int, help="hard cap on result pages (default: per-provider env var)")
    ap.add_argument("--dry-run", action="store_true", help="do not write to the database")
    ap.add_argument("--purge", metavar="SOURCE", help="delete all stored rows from SOURCE (e.g. snapshot), then exit")
    args = ap.parse_args(argv)

    settings = get_settings()
    if args.purge:
        try:
            conn = connect(settings.database_url)
            try:
                print(f"purged {purge_source(conn, args.purge)} rows with source='{args.purge}'")
            finally:
                conn.close()
        except DatabaseUnavailable as e:
            print(f"ERROR: {e}")
            return 1
        return 0
    name = (args.provider or settings.flight_provider).lower()
    try:
        provider = get_provider(name, settings)
        stats = run(settings, provider, hours=args.hours, max_pages=args.max_pages, dry_run=args.dry_run)
    except (ProviderError, DatabaseUnavailable) as e:
        print(f"ERROR: {e}")
        return 1

    pct = 100 * stats["with_gate"] / stats["flights"] if stats["flights"] else 0
    print(f"provider:   {stats['provider']}")
    print(f"pages:      {stats['pages']}" + ("   (cap reached, more pages exist)" if stats["more_available"] else ""))
    print(f"flights:    {stats['flights']}   with gate: {stats['with_gate']} ({pct:.0f}%)")
    print(f"stored:     {stats['stored']}" + ("   (dry run: nothing written)" if args.dry_run else ""))
    if stats["raw_pruned"]:
        print(f"raw files pruned (>30 days): {stats['raw_pruned']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
