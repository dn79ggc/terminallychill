from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assumptions import get_assumptions
from app.graph import get_graph
from app.model import forecast as build_forecast
from app.ranking import rank
from app.routes.deps import FlightLoader, get_flight_loader, load_or_503
from app.timeutil import require_aware

router = APIRouter(prefix="/api")


@router.get("/recommend")
def recommend(
    gate: str,
    boarding: datetime,
    limit: int = Query(3, ge=1, le=10),
    loader: FlightLoader = Depends(get_flight_loader),
) -> dict:
    try:
        boarding = require_aware(boarding, "boarding")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    now = datetime.now(timezone.utc)
    minutes = max(5.0, (boarding - now).total_seconds() / 60)
    buckets = min(12 * 60 // 5, max(1, math.ceil(minutes / 5)))
    hours = buckets * 5 / 60
    loaded = load_or_503(loader, now, now + timedelta(hours=hours))
    graph = get_graph()
    assumptions = get_assumptions()
    try:
        built = build_forecast(loaded.flights, graph, assumptions, now, hours)
        result = rank(gate, boarding, now, built, graph, assumptions, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return result.to_public(loaded.data_source())
