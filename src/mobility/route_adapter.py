"""
Route Adapter Module.

Converts Google Maps Routes API MapsRouteResponse objects into the
RouteCandidate domain model expected by the Route Evaluation Engine.

IMPORTANT — Fabrication Policy:
- Only fields that Maps API directly provides are populated with live data.
- Fields Maps does NOT provide are either left at documented defaults or
  estimated using explicit, documented heuristics clearly marked as ESTIMATED.
- No value is silently invented.

Historical ML Integration:
- Coordinates from Google Maps are NOT the same as Uber Movement ward IDs.
- Until a geographic coordinate-to-ward mapping layer exists, historical
  ML enrichment is disabled for arbitrary Maps API coordinates.
- When enabled (via ward_id lookup), `get_historical_mobility_signal()` is
  called and attached as `historical_mobility_signal`.
"""

from typing import Optional, Dict, Any
from src.mobility.models import MapsRouteResponse, TravelMode
from src.decision_engine.models import RouteCandidate


# ---------------------------------------------------------------------------
# Congestion estimation heuristics (ESTIMATED, not live Maps data)
# ---------------------------------------------------------------------------
# Driving: if traffic-aware duration significantly exceeds static, flag congestion.
# Maps provides these durations; congestion_score is derived.
# Transit/Walk: typically low congestion by design.

def _estimate_drive_congestion(response: MapsRouteResponse) -> float:
    """Estimate congestion score (0.0-1.0) from traffic vs. static duration ratio.

    ESTIMATED: Derived from Maps-provided durations. Not a Maps-provided field.
    """
    if not response.has_traffic_data or response.static_duration_seconds == 0:
        return 0.5  # Unknown — use neutral value
    ratio = response.total_duration_seconds / response.static_duration_seconds
    if ratio <= 1.05:
        return 0.1  # Free-flow
    elif ratio <= 1.20:
        return 0.3
    elif ratio <= 1.40:
        return 0.5
    elif ratio <= 1.65:
        return 0.7
    else:
        return 0.9  # Severe congestion


def _estimate_reliability(mode: TravelMode, congestion_score: float) -> float:
    """Estimate reliability score (0.0-1.0) by mode and congestion.

    ESTIMATED: Maps does not provide a reliability score.
    Transit typically has higher schedule reliability than road-based modes.
    """
    if mode == TravelMode.TRANSIT:
        return 0.85
    elif mode == TravelMode.WALK:
        return 0.99
    else:  # DRIVE
        return max(0.2, 0.95 - (congestion_score * 0.65))


def _estimate_disruption_risk(mode: TravelMode) -> float:
    """Estimate disruption risk (0.0-1.0) by mode.

    ESTIMATED: Maps does not provide disruption probability.
    """
    if mode == TravelMode.WALK:
        return 0.02
    elif mode == TravelMode.TRANSIT:
        return 0.08
    else:  # DRIVE
        return 0.12


def _estimate_drive_cost(distance_meters: int) -> float:
    """Estimate indicative cab/auto cost (INR) from distance.

    ESTIMATED: Maps does not provide pricing.
    Uses a rough Bengaluru cab base fare heuristic.
    Base: INR 50, per km: INR 16.
    """
    km = distance_meters / 1000.0
    return round(50.0 + km * 16.0, 0)


# ---------------------------------------------------------------------------
# Mode-specific adapters
# ---------------------------------------------------------------------------

def adapt_drive_route(response: MapsRouteResponse, index: int) -> RouteCandidate:
    """Convert a DRIVE mode MapsRouteResponse into a RouteCandidate.

    Live Maps fields used:   total_duration_seconds, static_duration_seconds,
                             distance_meters, has_traffic_data
    Estimated fields:        congestion_score, reliability_score, disruption_risk, cost
    Not applicable:          walking_minutes, transfers
    """
    congestion = _estimate_drive_congestion(response)
    reliability = _estimate_reliability(TravelMode.DRIVE, congestion)
    cost = _estimate_drive_cost(response.distance_meters)
    description = response.description or f"DRIVE route {index + 1}"

    return RouteCandidate(
        route_id=f"maps_drive_{index}",
        mode="cab",  # DRIVE defaults to cab/rideshare framing
        travel_time_minutes=round(response.total_duration_seconds / 60.0, 1),
        cost=cost,
        walking_minutes=0.0,
        transfers=0,
        congestion_score=congestion,
        reliability_score=reliability,
        disruption_risk=_estimate_disruption_risk(TravelMode.DRIVE),
        historical_mobility_signal=None,  # Requires ward ID mapping — disabled by default
    )


def adapt_transit_route(response: MapsRouteResponse, index: int) -> RouteCandidate:
    """Convert a TRANSIT mode MapsRouteResponse into a RouteCandidate.

    Live Maps fields used:   total_duration_seconds, walking_duration_seconds,
                             transit_legs, transfers
    Estimated fields:        congestion_score, reliability_score, disruption_risk, cost
    Not applicable:          has_traffic_data (transit ignores traffic)
    """
    walking_minutes = round(response.walking_duration_seconds / 60.0, 1)
    congestion = 0.15  # Transit is largely isolated from road congestion
    reliability = _estimate_reliability(TravelMode.TRANSIT, congestion)

    return RouteCandidate(
        route_id=f"maps_transit_{index}",
        mode="metro" if response.transit_legs > 0 else "bus",
        travel_time_minutes=round(response.total_duration_seconds / 60.0, 1),
        cost=25.0,  # Bengaluru Metro/BMTC indicative fare. ESTIMATED.
        walking_minutes=walking_minutes,
        transfers=response.transfers,
        congestion_score=congestion,
        reliability_score=reliability,
        disruption_risk=_estimate_disruption_risk(TravelMode.TRANSIT),
        historical_mobility_signal=None,
    )


def adapt_walk_route(response: MapsRouteResponse, index: int) -> RouteCandidate:
    """Convert a WALK mode MapsRouteResponse into a RouteCandidate.

    Live Maps fields used:   total_duration_seconds, distance_meters
    Estimated fields:        congestion_score, reliability_score, disruption_risk
    Not applicable:          cost (walking is free), transfers
    """
    return RouteCandidate(
        route_id=f"maps_walk_{index}",
        mode="walking",
        travel_time_minutes=round(response.total_duration_seconds / 60.0, 1),
        cost=0.0,
        walking_minutes=round(response.total_duration_seconds / 60.0, 1),
        transfers=0,
        congestion_score=0.05,
        reliability_score=_estimate_reliability(TravelMode.WALK, 0.05),
        disruption_risk=_estimate_disruption_risk(TravelMode.WALK),
        historical_mobility_signal=None,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

ADAPTERS = {
    TravelMode.DRIVE: adapt_drive_route,
    TravelMode.TRANSIT: adapt_transit_route,
    TravelMode.WALK: adapt_walk_route,
}


def field_provenance(mode: TravelMode) -> Dict[str, str]:
    """
    Declare which RouteCandidate fields are live Maps data vs heuristic.

    Values: "live" | "heuristic" | "n/a"
    Does not invent Maps values — documents adapter policy only.
    """
    if mode == TravelMode.DRIVE:
        return {
            "travel_time_minutes": "live",
            "distance_meters": "live",
            "has_traffic_data": "live",
            "congestion_score": "heuristic",
            "reliability_score": "heuristic",
            "disruption_risk": "heuristic",
            "cost": "heuristic",
            "walking_minutes": "n/a",
            "transfers": "n/a",
            "data_source": "google_maps_routes",
        }
    if mode == TravelMode.TRANSIT:
        return {
            "travel_time_minutes": "live",
            "distance_meters": "live",
            "walking_minutes": "live",
            "transfers": "live",
            "transit_legs": "live",
            "congestion_score": "heuristic",
            "reliability_score": "heuristic",
            "disruption_risk": "heuristic",
            "cost": "heuristic",
            "data_source": "google_maps_routes",
        }
    # WALK
    return {
        "travel_time_minutes": "live",
        "distance_meters": "live",
        "walking_minutes": "live",
        "cost": "heuristic",  # Maps does not price walking; adapter sets 0.0 explicitly
        "congestion_score": "heuristic",
        "reliability_score": "heuristic",
        "disruption_risk": "heuristic",
        "transfers": "n/a",
        "data_source": "google_maps_routes",
    }


def adapt_maps_response(response: MapsRouteResponse) -> RouteCandidate:
    """Dispatch a MapsRouteResponse to the correct mode adapter.

    Args:
        response (MapsRouteResponse): Parsed Maps route.

    Returns:
        RouteCandidate: Route candidate ready for evaluation engine.
    """
    adapter_fn = ADAPTERS.get(response.mode)
    if adapter_fn is None:
        raise ValueError(f"No adapter registered for travel mode: {response.mode}")
    return adapter_fn(response, response.route_index)
