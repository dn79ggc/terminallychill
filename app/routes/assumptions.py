from __future__ import annotations

from fastapi import APIRouter

from app.assumptions import get_assumptions

router = APIRouter(prefix="/api")


@router.get("/assumptions")
def assumptions() -> dict:
    return get_assumptions().to_public()
