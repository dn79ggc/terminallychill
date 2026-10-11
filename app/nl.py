"""Turn one typed sentence into a gate and a boarding time. Text only.

Gemini never receives a photo. The explanation sent back to the traveler is
built from our ranking numbers, so a model reply cannot invent a crowd index.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import httpx

from app.assumptions import get_assumptions
from app.config import Settings, get_settings
from app.counts import forecast_with_corrections
from app.graph import get_graph, parse_gate
from app.ranking import Recommendation, rank
from app.repo import FlightLoad

MAX_TEXT = 500
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AskUnavailable(Exception):
    """The key is missing or Gemini did not answer."""


class AskUnconfigured(AskUnavailable):
    """GEMINI_API_KEY is not set. The rest of the app still runs."""


class MalformedModel(Exception):
    """The model reply was not a gate and a usable number of hours."""


def extract_parameters(text: str, settings: Settings | None = None, post=None) -> dict:
    settings = settings or get_settings()
    if not settings.gemini_api_key:
        raise AskUnconfigured("missing key")
    sentence = _sentence(text)
    raw = (post or _post_gemini)(sentence, settings)
    return validate_parameters(raw)


def validate_parameters(raw: str) -> dict:
    try:
        parsed = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise MalformedModel("not json") from exc
    if not isinstance(parsed, dict):
        raise MalformedModel("not an object")
    gate = parsed.get("gate")
    hours = parsed.get("hours")
    if not isinstance(gate, str) or isinstance(hours, bool) or not isinstance(hours, (int, float)):
        raise MalformedModel("missing fields")
    if not 0 < float(hours) <= 12:
        raise MalformedModel("hours out of range")
    parsed_gate = parse_gate(gate)
    if parsed_gate is None:
        raise MalformedModel("gate")
    preferences = parsed.get("preferences", "")
    if preferences is None:
        preferences = ""
    if not isinstance(preferences, str):
        raise MalformedModel("preferences")
    label = f"{parsed_gate[0]}{parsed_gate[1]}"
    return {"gate": label, "hours": float(hours), "preferences": preferences.strip()[:200]}


def answer(text: str, loaded: FlightLoad, now: datetime, settings: Settings | None = None, post=None) -> dict:
    parameters = extract_parameters(text, settings, post)
    boarding = now + timedelta(hours=parameters["hours"])
    graph = get_graph()
    assumptions = get_assumptions()
    try:
        built = forecast_with_corrections(
            loaded.flights, graph, assumptions, now, _window_hours(parameters["hours"]), now
        )
        result = rank(parameters["gate"], boarding, now, built, graph, assumptions, limit=3)
    except ValueError as exc:
        raise MalformedModel(str(exc)) from exc
    return {
        "text": _sentence(text),
        "parameters": parameters,
        "recommendation": result.to_public(loaded.data_source()),
        "explanation": explanation(result),
    }


def _window_hours(hours: float) -> float:
    buckets = math.ceil(hours * 60 / 5 - 1e-9)
    buckets = min(12 * 60 // 5, max(1, buckets))
    return buckets * 5 / 60


def explanation(result: Recommendation) -> str:
    if not result.supported or not result.spots:
        return result.warnings[0] if result.warnings else "No quiet spot is available for that request."
    spot = result.spots[0]
    because = "; ".join(spot.reasons) if spot.reasons else "It ranks first on the forecast."
    return f"{spot.label}: {because}. Crowd index now is {spot.crowd_index_now}."


def _sentence(text: str) -> str:
    sentence = (text or "").strip()
    if not sentence or len(sentence) > MAX_TEXT:
        raise MalformedModel("text")
    return sentence


def _strip_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def _post_gemini(sentence: str, settings: Settings) -> str:
    url = GEMINI_URL.format(model=settings.gemini_model)
    prompt = (
        "Extract a gate request from the sentence. Reply as JSON with keys "
        "gate (letters and digits, such as B12), hours (a number, how long until boarding), "
        "and preferences (a short phrase, or an empty string). "
        "Use only a gate that the sentence actually names. Do not invent one.\n"
        f"Sentence: {sentence}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "gate": {"type": "string"},
                    "hours": {"type": "number"},
                    "preferences": {"type": "string"},
                },
                "required": ["gate", "hours"],
            },
        },
    }
    headers = {"x-goog-api-key": settings.gemini_api_key or "", "content-type": "application/json"}
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=20)
    except httpx.HTTPError as exc:
        raise AskUnavailable("request failed") from exc
    if response.status_code != 200:
        raise AskUnavailable("request failed")
    try:
        payload = response.json()
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AskUnavailable("request failed") from exc


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
