"""Synthetic sample data (no network, no key). Safe to commit and safe for the public demo.

data/sample/atl_synthetic.json stores each flight as `offset_min` from "now", so the
snapshot always looks current. Every row is invented; none comes from a real provider.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

from app.models import Flight, concourse_of

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "sample" / "atl_synthetic.json"


class SnapshotProvider:
    name = "snapshot"
    cache_raw = False

    def __init__(self, path: Path = DEFAULT_FILE, now: Callable[[], datetime] | None = None):
        self._path = Path(path)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.more_available = False

    def pages(self, start: datetime, end: datetime, max_pages: int) -> Iterator[dict]:
        body = json.loads(self._path.read_text(encoding="utf-8"))
        body["_generated_at"] = self._now().replace(second=0, microsecond=0).isoformat()
        yield body

    def parse(self, page: dict) -> list[Flight]:
        base = datetime.fromisoformat(page["_generated_at"])
        out: list[Flight] = []
        for fl in page["flights"]:
            sched = base + timedelta(minutes=fl["offset_min"])
            delay = fl.get("delay_s") or 0
            gate = fl.get("gate")
            out.append(
                Flight(
                    uid=f"snapshot:{fl['ident']}",
                    ident=fl["ident"],
                    operator=fl.get("operator"),
                    gate=gate,
                    concourse=concourse_of(gate),
                    terminal=fl.get("terminal"),
                    aircraft_type=fl.get("aircraft_type"),
                    scheduled_out=sched,
                    estimated_out=sched + timedelta(seconds=delay),
                    delay_s=delay,
                    cancelled=bool(fl.get("cancelled")),
                    source=self.name,
                )
            )
        return out
