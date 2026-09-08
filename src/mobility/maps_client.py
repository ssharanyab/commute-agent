"""
Google Maps Routes API HTTP Client.

Sends requests to the Routes API v2 and returns structured MapsRouteResponse objects.

Security:
- API key is read ONLY from the GOOGLE_MAPS_API_KEY environment variable.
- The key is never logged, printed, or included in exception messages.
- Authorization headers are stripped from any debug output.
"""

import os
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta

import requests

from src.mobility.models import (
    MapsRouteRequest,
    MapsRouteResponse,
    MapsRouteLeg,
    TravelMode,
)

logger = logging.getLogger(__name__)

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Field mask: only request the fields we actually use
FIELD_MASK = (
    "routes.duration,"
    "routes.staticDuration,"
    "routes.distanceMeters,"
    "routes.description,"
    "routes.polyline.encodedPolyline,"
    "routes.routeToken,"
    "routes.legs.duration,"
    "routes.legs.distanceMeters,"
    "routes.legs.stepsOverview,"
    "routes.travelAdvisory"
)

TRANSIT_FIELD_MASK = (
    "routes.duration,"
    "routes.staticDuration,"
    "routes.distanceMeters,"
    "routes.description,"
    "routes.polyline.encodedPolyline,"
    "routes.routeToken,"
    "routes.legs.duration,"
    "routes.legs.distanceMeters,"
    "routes.legs.steps.travelMode,"
    "routes.legs.steps.staticDuration,"
    "routes.legs.steps.distanceMeters,"
    "routes.legs.steps.navigationInstruction,"
    "routes.legs.steps.transitDetails"
)

PLACEHOLDER_KEYS = {"", "your_key_here", "changeme"}


class MapsAPIError(Exception):
    """Raised for structured Maps API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class MissingAPIKeyError(MapsAPIError):
    """Raised when GOOGLE_MAPS_API_KEY is not configured."""
    pass


class NoRoutesFoundError(MapsAPIError):
    """Raised when Maps API returns no routes."""
    pass


def _maybe_load_dotenv() -> None:
    """Load .env into process env if Maps key is unset. Never logs secrets."""
    existing = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if existing and existing not in PLACEHOLDER_KEYS:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass


def _normalize_departure_time(departure_time: Optional[str]) -> str:
    """
    Return an RFC3339 UTC timestamp acceptable to Routes API TRAFFIC_AWARE.

    Timezone rules (Bengaluru commute MVP):
    - Explicit Z / offset → convert to UTC.
    - Naive ISO (no offset) → interpret as Asia/Kolkata (IST).
    Past / empty / invalid timestamps are clamped to now + 60 seconds
    (Routes API requires a strictly future departureTime).
    """
    from zoneinfo import ZoneInfo

    now = datetime.now(timezone.utc)
    future_floor = now + timedelta(seconds=60)

    def _clamp_future() -> str:
        return future_floor.strftime("%Y-%m-%dT%H:%M:%SZ")

    if not departure_time or not str(departure_time).strip():
        return _clamp_future()
    raw = str(departure_time).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        utc = parsed.astimezone(timezone.utc)
        # Treat "now" / near-past the same as past — Maps rejects non-future.
        if utc < future_floor:
            return _clamp_future()
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return _clamp_future()


class MapsClient:
    """Lightweight HTTP client for the Google Maps Routes API v2.

    Does NOT contain scoring or business logic — purely API communication
    and structured response parsing.
    """

    def __init__(self, api_key: Optional[str] = None, timeout_seconds: int = 15):
        if api_key is None:
            _maybe_load_dotenv()
        raw_key = (api_key if api_key is not None else os.environ.get("GOOGLE_MAPS_API_KEY", ""))
        raw_key = (raw_key or "").strip()
        if not raw_key or raw_key in PLACEHOLDER_KEYS:
            raise MissingAPIKeyError(
                "GOOGLE_MAPS_API_KEY environment variable is not set. "
                "Copy .env.example to .env and provide a valid key."
            )
        self._api_key = raw_key
        self._timeout = timeout_seconds

    def _safe_headers(self) -> Dict[str, str]:
        """Return request headers without exposing the API key in any logs."""
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
        }

    def _build_waypoint(self, location: str) -> Dict[str, Any]:
        """Build a Maps API waypoint from an address or lat/lng string."""
        location = location.strip()
        # Detect lat,lng format (e.g., "12.9716,77.5946")
        parts = location.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lng = float(parts[1].strip())
                return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
            except ValueError:
                pass
        return {"address": location}

    def _parse_duration_seconds(self, duration_str: Optional[str]) -> int:
        """Parse Maps API duration string '123s' to int seconds."""
        if not duration_str:
            return 0
        return int(str(duration_str).rstrip("s"))

    def _parse_transit_legs(self, legs: List[Dict]) -> Tuple[int, int, int]:
        """
        Parse transit leg steps to count transit segments, transfers, and walking duration.

        Returns:
            Tuple[transit_leg_count, transfer_count, total_walking_seconds]
        """
        transit_count = 0
        walking_seconds = 0

        for leg in legs:
            for step in leg.get("steps", []):
                if step.get("transitDetails"):
                    transit_count += 1
                if step.get("travelMode") == "WALK":
                    walking_seconds += self._parse_duration_seconds(
                        step.get("staticDuration") or step.get("duration")
                    )

        transfers = max(0, transit_count - 1)
        return transit_count, transfers, walking_seconds

    def _extract_transit_summary(self, legs: List[Dict]) -> Optional[str]:
        """Build a short live transit summary from step transitDetails (if present)."""
        parts: List[str] = []
        for leg in legs:
            for step in leg.get("steps", []):
                details = step.get("transitDetails") or {}
                line = (details.get("transitLine") or {})
                name = line.get("nameShort") or line.get("name")
                vehicle = ((line.get("vehicle") or {}).get("type"))
                if name and vehicle:
                    parts.append(f"{vehicle}:{name}")
                elif name:
                    parts.append(str(name))
                elif vehicle:
                    parts.append(str(vehicle))
        if not parts:
            return None
        seen = set()
        unique = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return " + ".join(unique)

    def _parse_routes(self, raw_routes: List[Dict], mode: TravelMode) -> List[MapsRouteResponse]:
        """Parse raw Maps API route list into structured MapsRouteResponse objects."""
        parsed = []
        for i, route in enumerate(raw_routes):
            duration_secs = self._parse_duration_seconds(route.get("duration"))
            static_duration_secs = self._parse_duration_seconds(
                route.get("staticDuration", route.get("duration"))
            )
            has_traffic = (
                "duration" in route
                and route.get("staticDuration") is not None
                and route.get("duration") != route.get("staticDuration")
            )
            distance_m = route.get("distanceMeters", 0) or 0
            description = route.get("description")
            legs_raw = route.get("legs", []) or []

            parsed_legs = []
            for leg in legs_raw:
                parsed_legs.append(MapsRouteLeg(
                    duration_seconds=self._parse_duration_seconds(leg.get("duration")),
                    distance_meters=leg.get("distanceMeters", 0) or 0,
                ))

            transit_legs, transfers, walking_secs = 0, 0, 0
            if mode == TravelMode.TRANSIT:
                transit_legs, transfers, walking_secs = self._parse_transit_legs(legs_raw)
                transit_summary = self._extract_transit_summary(legs_raw)
                if transit_summary and not description:
                    description = transit_summary
                elif transit_summary and description:
                    description = f"{description} ({transit_summary})"
            elif mode == TravelMode.WALK:
                walking_secs = duration_secs

            encoded_polyline = None
            polyline_obj = route.get("polyline")
            if isinstance(polyline_obj, dict):
                raw_poly = polyline_obj.get("encodedPolyline")
                if isinstance(raw_poly, str) and raw_poly.strip():
                    encoded_polyline = raw_poly
            raw_token = route.get("routeToken")
            route_token = raw_token if isinstance(raw_token, str) and raw_token.strip() else None

            parsed.append(MapsRouteResponse(
                route_index=i,
                mode=mode,
                total_duration_seconds=duration_secs,
                static_duration_seconds=static_duration_secs,
                distance_meters=int(distance_m),
                has_traffic_data=has_traffic,
                walking_duration_seconds=walking_secs,
                transit_legs=transit_legs,
                transfers=transfers,
                description=description,
                legs=parsed_legs,
                encoded_polyline=encoded_polyline,
                route_token=route_token,
                raw_response=route,
            ))
        return parsed

    def _build_request_body(self, request: MapsRouteRequest) -> Dict[str, Any]:
        """Construct the Routes API JSON body (testable without HTTP)."""
        body: Dict[str, Any] = {
            "origin": self._build_waypoint(request.origin),
            "destination": self._build_waypoint(request.destination),
            "travelMode": request.mode.value,
            "computeAlternativeRoutes": bool(request.compute_alternatives),
        }

        if request.mode == TravelMode.DRIVE:
            body["routingPreference"] = "TRAFFIC_AWARE"
            body["departureTime"] = _normalize_departure_time(request.departure_time)
        elif request.mode == TravelMode.TRANSIT:
            body["departureTime"] = _normalize_departure_time(request.departure_time)
        # WALK: no traffic preference / departure required

        return body

    def compute_routes(self, request: MapsRouteRequest) -> List[MapsRouteResponse]:
        """Execute a Maps Routes API call and return structured responses.

        Raises:
            MissingAPIKeyError: If API key is absent.
            NoRoutesFoundError: If no routes are returned.
            MapsAPIError: For HTTP errors, quota errors, or malformed responses.
        """
        field_mask = TRANSIT_FIELD_MASK if request.mode == TravelMode.TRANSIT else FIELD_MASK
        body = self._build_request_body(request)

        headers = self._safe_headers()
        headers["X-Goog-FieldMask"] = field_mask

        try:
            response = requests.post(
                ROUTES_API_URL,
                json=body,
                headers=headers,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout:
            raise MapsAPIError("Maps API request timed out.")
        except requests.exceptions.ConnectionError as e:
            raise MapsAPIError(f"Network error connecting to Maps API: {type(e).__name__}")

        if response.status_code in (401, 403):
            raise MapsAPIError(
                "Maps API authentication failed. Check GOOGLE_MAPS_API_KEY.",
                response.status_code,
            )
        if response.status_code == 429:
            raise MapsAPIError("Maps API quota exceeded.", response.status_code)
        if response.status_code != 200:
            detail = ""
            try:
                err = response.json().get("error", {})
                msg = err.get("message")
                if msg:
                    detail = f" {msg}"
            except Exception:
                detail = ""
            raise MapsAPIError(
                f"Maps API returned HTTP {response.status_code}.{detail}",
                response.status_code,
            )

        try:
            data = response.json()
        except Exception:
            raise MapsAPIError("Maps API returned non-JSON response.")

        if not isinstance(data, dict):
            raise MapsAPIError("Maps API returned malformed JSON payload.")

        raw_routes = data.get("routes", [])
        if not raw_routes:
            raise NoRoutesFoundError(
                f"Maps API returned no routes for {request.mode.value}: "
                f"'{request.origin}' -> '{request.destination}'"
            )
        if not isinstance(raw_routes, list):
            raise MapsAPIError("Maps API returned malformed routes field.")

        return self._parse_routes(raw_routes, request.mode)
