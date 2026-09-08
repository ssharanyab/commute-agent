"""
Structured data models for the Mobility layer.

These represent raw Google Maps Routes API response data, distinct from the
Route Evaluation Engine's RouteCandidate domain model.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class TravelMode(str, Enum):
    """Supported travel modes for Maps API requests."""
    DRIVE = "DRIVE"
    TRANSIT = "TRANSIT"
    WALK = "WALK"


@dataclass
class MapsRouteLeg:
    """Structured representation of a single leg within a Maps route."""
    start_address: Optional[str] = None
    end_address: Optional[str] = None
    duration_seconds: int = 0
    distance_meters: int = 0
    # Walking sub-segment within a leg (for transit legs)
    walking_duration_seconds: int = 0
    walking_distance_meters: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_address": self.start_address,
            "end_address": self.end_address,
            "duration_seconds": self.duration_seconds,
            "distance_meters": self.distance_meters,
            "walking_duration_seconds": self.walking_duration_seconds,
            "walking_distance_meters": self.walking_distance_meters,
        }


@dataclass
class MapsRouteResponse:
    """Structured representation of a single route returned by the Maps Routes API.

    Fields reflect only what the API actually provides — no fabricated values.
    """
    route_index: int = 0
    mode: TravelMode = TravelMode.DRIVE
    total_duration_seconds: int = 0
    static_duration_seconds: int = 0  # Duration without traffic
    distance_meters: int = 0
    has_traffic_data: bool = False
    walking_duration_seconds: int = 0     # Total walking across all legs
    transit_legs: int = 0                 # Number of transit segments (TRANSIT mode only)
    transfers: int = 0                    # transfers = transit_legs - 1 (if > 0)
    description: Optional[str] = None
    legs: List[MapsRouteLeg] = field(default_factory=list)
    # Google-provided geometry / navigation identity (optional — not always present)
    encoded_polyline: Optional[str] = None
    route_token: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None  # Original API payload for debugging

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_index": self.route_index,
            "mode": self.mode.value,
            "total_duration_seconds": self.total_duration_seconds,
            "static_duration_seconds": self.static_duration_seconds,
            "distance_meters": self.distance_meters,
            "has_traffic_data": self.has_traffic_data,
            "walking_duration_seconds": self.walking_duration_seconds,
            "transit_legs": self.transit_legs,
            "transfers": self.transfers,
            "description": self.description,
            "legs": [leg.to_dict() for leg in self.legs],
            "encoded_polyline": self.encoded_polyline,
            "route_token": self.route_token,
        }


@dataclass
class MapsRouteRequest:
    """Parameters for a Maps Routes API request."""
    origin: str          # Address or lat/lng string
    destination: str     # Address or lat/lng string
    mode: TravelMode = TravelMode.DRIVE
    departure_time: Optional[str] = None  # ISO 8601 or None for 'now'
    compute_alternatives: bool = True

    def cache_key(self) -> str:
        """Generate a deterministic cache key for this request."""
        return f"{self.mode.value}::{self.origin}::{self.destination}::{self.departure_time}::{self.compute_alternatives}"
