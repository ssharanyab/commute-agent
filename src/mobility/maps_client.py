"""
Google Maps Routes API HTTP Client.

Sends requests to the Routes API v2 and returns structured MapsRouteResponse objects.

Security:
- API key is read ONLY from the GOOGLE_MAPS_API_KEY environment variable.
- The key is never logged, printed, or included in exception messages.
- Authorization headers are stripped from any debug output.
"""

import os
import time
import hashlib
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone

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
    "routes.legs.duration,"
    "routes.legs.distanceMeters,"
    "routes.legs.steps"
)


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


class MapsClient:
    """Lightweight HTTP client for the Google Maps Routes API v2.

    Does NOT contain scoring or business logic — purely API communication
    and structured response parsing.
    """

    def __init__(self, api_key: Optional[str] = None, timeout_seconds: int = 10):
        raw_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
        if not raw_key or raw_key.strip() == "your_key_here":
            raise MissingAPIKeyError(
                "GOOGLE_MAPS_API_KEY environment variable is not set. "
                "Copy .env.example to .env and provide a valid key."
            )
        self._api_key = raw_key.strip()
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
        return int(duration_str.rstrip("s"))

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
                nav_instruction = step.get("navigationInstruction", {})
                if step.get("transitDetails"):
                    transit_count += 1
                if step.get("travelMode") == "WALK":
                    walking_seconds += self._parse_duration_seconds(step.get("staticDuration"))

        transfers = max(0, transit_count - 1)
        return transit_count, transfers, walking_seconds

    def _parse_routes(self, raw_routes: List[Dict], mode: TravelMode) -> List[MapsRouteResponse]:
        """Parse raw Maps API route list into structured MapsRouteResponse objects."""
        parsed = []
        for i, route in enumerate(raw_routes):
            duration_secs = self._parse_duration_seconds(route.get("duration"))
            static_duration_secs = self._parse_duration_seconds(route.get("staticDuration", route.get("duration")))
            has_traffic = "duration" in route and route.get("duration") != route.get("staticDuration")
            distance_m = route.get("distanceMeters", 0)
            description = route.get("description")
            legs_raw = route.get("legs", [])

            # Parse legs
            parsed_legs = []
            for leg in legs_raw:
                parsed_legs.append(MapsRouteLeg(
                    duration_seconds=self._parse_duration_seconds(leg.get("duration")),
                    distance_meters=leg.get("distanceMeters", 0),
                ))

            # Transit-specific: extract walking & transfer details
            transit_legs, transfers, walking_secs = 0, 0, 0
            if mode == TravelMode.TRANSIT:
                transit_legs, transfers, walking_secs = self._parse_transit_legs(legs_raw)
            elif mode == TravelMode.WALK:
                walking_secs = duration_secs  # All walking

            parsed.append(MapsRouteResponse(
                route_index=i,
                mode=mode,
                total_duration_seconds=duration_secs,
                static_duration_seconds=static_duration_secs,
                distance_meters=distance_m,
                has_traffic_data=has_traffic,
                walking_duration_seconds=walking_secs,
                transit_legs=transit_legs,
                transfers=transfers,
                description=description,
                legs=parsed_legs,
                raw_response=route,
            ))
        return parsed

    def compute_routes(self, request: MapsRouteRequest) -> List[MapsRouteResponse]:
        """Execute a Maps Routes API call and return structured responses.

        Args:
            request (MapsRouteRequest): Route request parameters.

        Returns:
            List[MapsRouteResponse]: Parsed route results.

        Raises:
            MissingAPIKeyError: If API key is absent.
            NoRoutesFoundError: If no routes are returned.
            MapsAPIError: For HTTP errors, quota errors, or malformed responses.
        """
        field_mask = TRANSIT_FIELD_MASK if request.mode == TravelMode.TRANSIT else FIELD_MASK

        body: Dict[str, Any] = {
            "origin": self._build_waypoint(request.origin),
            "destination": self._build_waypoint(request.destination),
            "travelMode": request.mode.value,
            "computeAlternativeRoutes": request.compute_alternatives,
        }

        if request.mode == TravelMode.DRIVE:
            body["routingPreference"] = "TRAFFIC_AWARE"
            if request.departure_time:
                body["departureTime"] = request.departure_time
            else:
                body["departureTime"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if request.mode == TravelMode.TRANSIT and request.departure_time:
            body["departureTime"] = request.departure_time

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

        if response.status_code == 401 or response.status_code == 403:
            raise MapsAPIError("Maps API authentication failed. Check GOOGLE_MAPS_API_KEY.", response.status_code)
        if response.status_code == 429:
            raise MapsAPIError("Maps API quota exceeded.", response.status_code)
        if response.status_code != 200:
            raise MapsAPIError(f"Maps API returned HTTP {response.status_code}.", response.status_code)

        try:
            data = response.json()
        except Exception:
            raise MapsAPIError("Maps API returned non-JSON response.")

        raw_routes = data.get("routes", [])
        if not raw_routes:
            raise NoRoutesFoundError(
                f"Maps API returned no routes for {request.mode.value}: '{request.origin}' -> '{request.destination}'"
            )

        return self._parse_routes(raw_routes, request.mode)
