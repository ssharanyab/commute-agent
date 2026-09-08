"""Live traffic / routing enrichment via existing Maps mobility service."""

from __future__ import annotations

from typing import Callable, List, Optional

from src.agent.capabilities import TrafficEnrichmentResult
from src.journey_builder.models import Journey
from src.mobility.models import TravelMode


EnricherFn = Callable[..., List]


def enrich_road_legs(
    journey: Journey,
    *,
    get_routes: Optional[EnricherFn] = None,
    departure_time: Optional[str] = None,
) -> List[TrafficEnrichmentResult]:
    """
    Enrich legs that declare needs_enrichment using existing Maps client.

    Does not invent traffic. If Maps is unavailable, returns explicit failures
    for those legs without fabricating durations.
    """
    results: List[TrafficEnrichmentResult] = []
    if get_routes is None:
        from src.mobility.service import get_candidate_routes as get_routes

    for req in journey.enrichment_requirements:
        if req.requirement_type != "road_geometry_time":
            continue
        if (
            req.from_lat is None
            or req.from_lon is None
            or req.to_lat is None
            or req.to_lon is None
        ):
            results.append(
                TrafficEnrichmentResult(
                    journey_id=journey.candidate_id,
                    leg_index=req.leg_index,
                    available=False,
                    reason="MISSING_COORDINATES",
                    provenance={"source": "traffic_capability"},
                )
            )
            continue

        origin = f"{req.from_lat},{req.from_lon}"
        destination = f"{req.to_lat},{req.to_lon}"
        mode = TravelMode.DRIVE
        try:
            candidates = get_routes(
                origin=origin,
                destination=destination,
                departure_time=departure_time,
                modes=[mode],
            )
        except Exception as exc:
            results.append(
                TrafficEnrichmentResult(
                    journey_id=journey.candidate_id,
                    leg_index=req.leg_index,
                    available=False,
                    reason=f"MAPS_UNAVAILABLE ({type(exc).__name__})",
                    provenance={"source": "google_maps_routes"},
                )
            )
            continue

        if not candidates:
            results.append(
                TrafficEnrichmentResult(
                    journey_id=journey.candidate_id,
                    leg_index=req.leg_index,
                    available=False,
                    reason="NO_ROUTES",
                    provenance={"source": "google_maps_routes"},
                )
            )
            continue

        best = candidates[0]
        results.append(
            TrafficEnrichmentResult(
                journey_id=journey.candidate_id,
                leg_index=req.leg_index,
                available=True,
                duration_minutes=float(best.travel_time_minutes),
                distance_meters=(
                    float(best.distance_meters)
                    if best.distance_meters is not None
                    else None
                ),
                traffic_info={
                    "congestion_score": best.congestion_score,
                    "mode": best.mode,
                },
                polyline=best.google_polyline,
                route_token=best.google_route_token,
                provenance={"source": "google_maps_routes"},
                reason="ok",
            )
        )
    return results
