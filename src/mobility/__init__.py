"""
Mobility Layer Package.

Provides Google Maps Routes API integration, structured route model adapters,
and a high-level service interface that produces RouteCandidate objects for the
Route Evaluation Engine.
"""

from src.mobility.service import get_candidate_routes
from src.mobility.models import MapsRouteRequest, MapsRouteResponse, MapsRouteLeg, TravelMode

__all__ = [
    "get_candidate_routes",
    "MapsRouteRequest",
    "MapsRouteResponse",
    "MapsRouteLeg",
    "TravelMode",
]
