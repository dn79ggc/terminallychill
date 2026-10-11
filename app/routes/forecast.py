from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assumptions import get_assumptions
from app.counts import forecast_with_corrections
from app.graph import get_graph
from app.routes.deps import FlightLoader, get_flight_loader, load_or_503
from app.timeutil import require_aware

router = APIRouter(prefix="/api")


@router.get("/forecast")
def forecast(
    concourse: str,
    start: datetime,
    hours: float = Query(gt=0, le=12),
    loader: FlightLoader = Depends(get_flight_loader),
) -> dict:
    graph = get_graph()
    if concourse.strip().upper() != graph.concourse:
        raise HTTPException(
            status_code=422,
            detail=f"Only concourse {graph.concourse} is supported in this version.",
        )
    try:
        start = require_aware(start, "start")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    loaded = load_or_503(loader, start, start + timedelta(hours=hours))
    try:
        result = forecast_with_corrections(
            loaded.flights, graph, get_assumptions(), start, hours, datetime.now(timezone.utc)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return result.to_public(loaded.data_source())
