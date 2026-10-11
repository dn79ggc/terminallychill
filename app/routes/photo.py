"""POST /api/photo. The image is counted in memory and then discarded. No UI."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.assumptions import get_assumptions
from app.counts import forecast_with_corrections, remember_count
from app.graph import get_graph
from app.routes.deps import FlightLoader, get_flight_loader, load_or_503
from app.vision import DetectorUnavailable, count_image_bytes, decode_image

router = APIRouter(prefix="/api")

MAX_BYTES = 5 * 1024 * 1024
WINDOW_HOURS = 3.0


@router.post("/photo")
async def photo(
    zone_id: str = Form(...),
    image: UploadFile = File(...),
    loader: FlightLoader = Depends(get_flight_loader),
) -> dict:
    graph = get_graph()
    zone = (zone_id or "").strip()
    if zone not in graph.zones:
        raise HTTPException(status_code=422, detail="Unknown zone.")
    _reject_content_type(image.content_type)
    data = await _read_limited(image)
    try:
        decode_image(data)
        count = count_image_bytes(data)
    except DetectorUnavailable:
        raise HTTPException(status_code=503, detail="Person detector is not configured.") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Upload an image file.") from None
    finally:
        data = b""

    now = datetime.now(timezone.utc)
    remember_count(now, zone, count)
    loaded = load_or_503(loader, now, now)
    try:
        built = forecast_with_corrections(
            loaded.flights, graph, get_assumptions(), now, WINDOW_HOURS, now
        )
        adjusted = built.index_at(zone, now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"zone_id": zone, "count": count, "adjusted_index": adjusted}


def _reject_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind in {"application/octet-stream"} or kind.startswith("image/"):
        return
    raise HTTPException(status_code=415, detail="Upload an image file.")


async def _read_limited(image: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            block = await image.read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_BYTES:
                raise HTTPException(status_code=413, detail="Image is larger than 5 MB.")
            chunks.append(block)
    finally:
        await image.close()
    if total == 0:
        raise HTTPException(status_code=422, detail="Upload an image file.")
    return b"".join(chunks)
