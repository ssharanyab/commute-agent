"""
Google Geocoding + Places API (New) helpers for Bengaluru (Phase 7I).

Uses GOOGLE_MAPS_API_KEY (same as Routes). Never logs the key.
Does not rank journeys — label → coordinates / suggestions only.

Places Autocomplete / Details use Places API (New):
  POST https://places.googleapis.com/v1/places:autocomplete
  GET  https://places.googleapis.com/v1/places/{place_id}
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from src.mobility.maps_client import (
    PLACEHOLDER_KEYS,
    MissingAPIKeyError,
    _maybe_load_dotenv,
)

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Places API (New) — not legacy maps/api/place/*
PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places"

# Bengaluru city center — location bias for Places / Geocoding.
BENGALURU_LAT = 12.9716
BENGALURU_LNG = 77.5946
BENGALURU_BIAS_RADIUS_M = 45000.0

_AUTOCOMPLETE_FIELD_MASK = (
    "suggestions.placePrediction.placeId,"
    "suggestions.placePrediction.text,"
    "suggestions.placePrediction.structuredFormat"
)
_DETAILS_FIELD_MASK = "id,displayName,formattedAddress,location,types,primaryType"


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    formatted_address: str
    provider: str = "google_geocoding"


@dataclass(frozen=True)
class PlaceSuggestion:
    place_id: str
    description: str
    main_text: str
    secondary_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "place_id": self.place_id,
            "description": self.description,
            "main_text": self.main_text,
            "secondary_text": self.secondary_text,
        }


@dataclass(frozen=True)
class PlaceDetails:
    place_id: str
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    types: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "place_id": self.place_id,
            "name": self.name,
            "formatted_address": self.formatted_address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "types": list(self.types),
        }


def _api_key() -> str:
    _maybe_load_dotenv()
    raw = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if not raw or raw in PLACEHOLDER_KEYS:
        raise MissingAPIKeyError(
            "GOOGLE_MAPS_API_KEY environment variable is not set."
        )
    return raw


def maps_api_key_configured() -> bool:
    try:
        _api_key()
        return True
    except MissingAPIKeyError:
        return False


def geocode_bengaluru(
    address: str,
    *,
    session: Optional[Any] = None,
    timeout_seconds: float = 8.0,
) -> Optional[GeocodeResult]:
    """
    Geocode a free-text address with India + Bengaluru bias.

    Returns None when no result / API error (caller falls back).
    """
    text = (address or "").strip()
    if not text:
        return None
    try:
        key = _api_key()
    except MissingAPIKeyError:
        logger.info(
            "geocode skipped input=%r reason=missing_api_key",
            text,
        )
        return None

    query = text
    lower = text.lower()
    if "bengaluru" not in lower and "bangalore" not in lower and "india" not in lower:
        query = f"{text}, Bengaluru, Karnataka, India"

    params = {
        "address": query,
        "key": key,
        "region": "in",
        "components": "country:IN",
        "bounds": (
            f"{BENGALURU_LAT - 0.45},{BENGALURU_LNG - 0.45}|"
            f"{BENGALURU_LAT + 0.45},{BENGALURU_LNG + 0.45}"
        ),
    }
    http = session or requests
    try:
        resp = http.get(GEOCODE_URL, params=params, timeout=timeout_seconds)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.info(
            "geocode failed input=%r error_category=http_error detail=%s",
            text,
            type(exc).__name__,
        )
        return None

    status = str(payload.get("status") or "")
    if status != "OK":
        logger.info(
            "geocode failed input=%r error_category=geocode_%s",
            text,
            status.lower() or "empty",
        )
        return None

    results = payload.get("results") or []
    if not results:
        return None

    best = results[0]
    loc = ((best.get("geometry") or {}).get("location")) or {}
    try:
        lat = float(loc["lat"])
        lng = float(loc["lng"])
    except (KeyError, TypeError, ValueError):
        logger.info(
            "geocode failed input=%r error_category=parse_error",
            text,
        )
        return None

    formatted = str(best.get("formatted_address") or text)
    logger.info(
        "geocode success input=%r provider=google_geocoding lat=%.5f lon=%.5f",
        text,
        lat,
        lng,
    )
    return GeocodeResult(
        latitude=lat,
        longitude=lng,
        formatted_address=formatted,
        provider="google_geocoding",
    )


def _places_headers(api_key: str, field_mask: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }


def _normalize_place_id(place_id: str) -> str:
    """Accept raw place id or resource name ``places/{id}``."""
    pid = (place_id or "").strip()
    if pid.startswith("places/"):
        pid = pid[len("places/") :]
    return pid


def _places_error_category(resp: Any, payload: Optional[Dict[str, Any]]) -> str:
    """Map Places (New) HTTP / JSON error to a short category (no secrets)."""
    status = getattr(resp, "status_code", None)
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        if isinstance(err, dict):
            status_text = str(err.get("status") or "").lower()
            if status_text:
                return f"places_{status_text}"
            msg = str(err.get("message") or "").lower()
            if "api key" in msg or "denied" in msg or "permission" in msg:
                return "places_permission_denied"
    if status == 403:
        return "places_permission_denied"
    if status == 401:
        return "places_unauthenticated"
    if status == 429:
        return "places_resource_exhausted"
    if status is not None and int(status) >= 400:
        return f"places_http_{status}"
    return "places_error"


def places_autocomplete(
    input_text: str,
    *,
    session: Optional[Any] = None,
    timeout_seconds: float = 8.0,
    limit: int = 6,
) -> Tuple[List[PlaceSuggestion], Optional[str]]:
    """
    Places Autocomplete (New) biased to Bengaluru.

    Returns (suggestions, error_category). error_category is None on success.
    """
    text = (input_text or "").strip()
    if len(text) < 2:
        return [], None
    try:
        key = _api_key()
    except MissingAPIKeyError:
        return [], "missing_api_key"

    body = {
        "input": text,
        "languageCode": "en",
        "includedRegionCodes": ["in"],
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": BENGALURU_LAT,
                    "longitude": BENGALURU_LNG,
                },
                "radius": BENGALURU_BIAS_RADIUS_M,
            }
        },
    }
    http = session or requests
    try:
        resp = http.post(
            PLACES_AUTOCOMPLETE_URL,
            headers=_places_headers(key, _AUTOCOMPLETE_FIELD_MASK),
            json=body,
            timeout=timeout_seconds,
        )
        payload = {}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        if getattr(resp, "status_code", 200) >= 400:
            cat = _places_error_category(resp, payload if isinstance(payload, dict) else None)
            logger.info(
                "places_autocomplete failed input=%r error_category=%s http=%s",
                text,
                cat,
                resp.status_code,
            )
            return [], cat
    except Exception as exc:
        logger.info(
            "places_autocomplete failed input=%r error_category=http_error detail=%s",
            text,
            type(exc).__name__,
        )
        return [], "http_error"

    if not isinstance(payload, dict):
        return [], "parse_error"

    out: List[PlaceSuggestion] = []
    for suggestion in payload.get("suggestions") or []:
        if not isinstance(suggestion, dict):
            continue
        pred = suggestion.get("placePrediction") or {}
        if not isinstance(pred, dict):
            continue
        place_id = _normalize_place_id(str(pred.get("placeId") or pred.get("place") or ""))
        if not place_id:
            continue
        text_obj = pred.get("text") or {}
        description = (
            str(text_obj.get("text") or "")
            if isinstance(text_obj, dict)
            else str(text_obj or "")
        )
        structured = pred.get("structuredFormat") or {}
        main = ""
        secondary = ""
        if isinstance(structured, dict):
            main_obj = structured.get("mainText") or {}
            sec_obj = structured.get("secondaryText") or {}
            main = (
                str(main_obj.get("text") or "")
                if isinstance(main_obj, dict)
                else str(main_obj or "")
            )
            secondary = (
                str(sec_obj.get("text") or "")
                if isinstance(sec_obj, dict)
                else str(sec_obj or "")
            )
        out.append(
            PlaceSuggestion(
                place_id=place_id,
                description=description or main,
                main_text=main or description,
                secondary_text=secondary,
            )
        )
        if len(out) >= max(1, limit):
            break
    return out, None


def place_details(
    place_id: str,
    *,
    session: Optional[Any] = None,
    timeout_seconds: float = 8.0,
) -> Tuple[Optional[PlaceDetails], Optional[str]]:
    """Resolve a place_id to coordinates via Places API (New) Place Details."""
    pid = _normalize_place_id(place_id)
    if not pid:
        return None, "invalid_place_id"
    try:
        key = _api_key()
    except MissingAPIKeyError:
        return None, "missing_api_key"

    url = f"{PLACES_DETAILS_URL}/{quote(pid, safe='')}"
    http = session or requests
    try:
        resp = http.get(
            url,
            headers=_places_headers(key, _DETAILS_FIELD_MASK),
            timeout=timeout_seconds,
        )
        payload: Dict[str, Any] = {}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        if getattr(resp, "status_code", 200) >= 400:
            cat = _places_error_category(resp, payload)
            logger.info(
                "place_details failed place_id=%r error_category=%s http=%s",
                pid,
                cat,
                resp.status_code,
            )
            return None, cat
    except Exception as exc:
        logger.info(
            "place_details failed place_id=%r error_category=http_error detail=%s",
            pid,
            type(exc).__name__,
        )
        return None, "http_error"

    if not isinstance(payload, dict):
        return None, "parse_error"

    loc = payload.get("location") or {}
    try:
        lat = float(loc["latitude"])
        lng = float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None, "parse_error"

    display = payload.get("displayName") or {}
    name = (
        str(display.get("text") or "")
        if isinstance(display, dict)
        else str(display or "")
    )
    types_raw = payload.get("types") or []
    types: Tuple[str, ...] = tuple(
        str(t) for t in types_raw if t
    ) if isinstance(types_raw, list) else ()
    primary = payload.get("primaryType")
    if primary and str(primary) not in types:
        types = types + (str(primary),)
    details = PlaceDetails(
        place_id=_normalize_place_id(str(payload.get("id") or pid)),
        name=name,
        formatted_address=str(payload.get("formattedAddress") or ""),
        latitude=lat,
        longitude=lng,
        types=types,
    )
    logger.info(
        "place_details success place_id=%r lat=%.5f lon=%.5f",
        pid,
        lat,
        lng,
    )
    return details, None
