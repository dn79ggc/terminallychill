from __future__ import annotations

from fastapi import APIRouter

from app.graph import get_graph

router = APIRouter(prefix="/api")


@router.get("/graph")
def graph() -> dict:
    return get_graph().raw
