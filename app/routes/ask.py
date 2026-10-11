"""POST /api/ask. One typed sentence in, a ranking and our own explanation out."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.nl import AskUnavailable, AskUnconfigured, MalformedModel, answer
from app.routes.deps import FlightLoader, get_flight_loader, load_or_503

router = APIRouter(prefix="/api")


class AskBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/ask")
def ask(body: AskBody, loader: FlightLoader = Depends(get_flight_loader)) -> dict:
    now = datetime.now(timezone.utc)
    # The flight window is filled in after Gemini names the hours. Load a full
    # window first so a short sentence cannot skip the database check.
    loaded = load_or_503(loader, now, now + timedelta(hours=12))
    try:
        return answer(body.text, loaded, now)
    except MalformedModel:
        raise HTTPException(
            status_code=422,
            detail="Could not read a gate and a boarding time from that request.",
        ) from None
    except AskUnconfigured:
        raise HTTPException(status_code=503, detail="Ask service is not configured.") from None
    except AskUnavailable:
        raise HTTPException(status_code=503, detail="Ask service is unavailable.") from None
