"""
Apply traffic enrichment results onto Journey legs and re-aggregate (Phase 6E).

Does not invent values on provider failure — marks duration unavailable/unknown.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.agent.capabilities import TrafficEnrichmentResult
from src.journey_builder.economics import (
    aggregate_journey_economics,
    annotate_leg_economics,
)
from src.journey_builder.models import Journey, JourneyLeg, ValueStatus
from src.network.models import DataProvenance, SourceType


def _maps_provenance(enrichment: TrafficEnrichmentResult) -> DataProvenance:
    from datetime import datetime, timezone

    src = (enrichment.provenance or {}).get("source") or "google_maps_routes"
    provider = (enrichment.provenance or {}).get("provider") or "Google Routes"
    notes = enrichment.reason or "road_geometry_time"
    route_mode = (enrichment.provenance or {}).get("route_mode")
    if route_mode:
        notes = f"{notes}; route_mode={route_mode}; provider={provider}"
    else:
        notes = f"{notes}; provider={provider}"
    return DataProvenance(
        source=str(src),
        source_type=SourceType.COMMERCIAL_API,
        retrieved_at=datetime.now(timezone.utc),
        notes=notes,
        confidence=0.85 if enrichment.available else 0.0,
    )


def apply_leg_enrichment(
    leg: JourneyLeg,
    enrichment: Optional[TrafficEnrichmentResult],
) -> JourneyLeg:
    """Write Maps duration/distance onto a road leg when enrichment succeeded."""
    if enrichment is None:
        return leg

    meta = dict(leg.metadata)
    if not enrichment.available:
        meta["enrichment_failure"] = {
            "reason": enrichment.reason,
            "provenance": dict(enrichment.provenance or {}),
        }
        # Keep prior distance; duration stays unknown — do not invent 0.
        return JourneyLeg(
            index=leg.index,
            mode=leg.mode,
            from_node_id=leg.from_node_id,
            to_node_id=leg.to_node_id,
            edge_id=leg.edge_id,
            edge_kind=leg.edge_kind,
            from_ref=leg.from_ref,
            to_ref=leg.to_ref,
            from_name=leg.from_name,
            to_name=leg.to_name,
            route_id=leg.route_id,
            provider=leg.provider,
            distance_meters=leg.distance_meters,
            is_transfer=leg.is_transfer,
            needs_enrichment=leg.needs_enrichment,
            estimated_departure=leg.estimated_departure,
            estimated_arrival=leg.estimated_arrival,
            waiting_seconds=leg.waiting_seconds,
            segment_role=leg.segment_role,
            cost_inr=leg.cost_inr,
            cost_status=leg.cost_status,
            duration_seconds=None,
            duration_status=ValueStatus.UNAVAILABLE.value
            if enrichment.reason
            else ValueStatus.UNKNOWN.value,
            walking_meters=leg.walking_meters,
            provenance=leg.provenance,
            metadata=meta,
        )

    dist = (
        float(enrichment.distance_meters)
        if enrichment.distance_meters is not None
        else leg.distance_meters
    )
    dur_s = (
        float(enrichment.duration_minutes) * 60.0
        if enrichment.duration_minutes is not None
        else None
    )
    meta["traffic_info"] = dict(enrichment.traffic_info or {})
    if enrichment.polyline:
        meta["polyline"] = enrichment.polyline
    if enrichment.route_token:
        meta["route_token"] = enrichment.route_token

    updated = JourneyLeg(
        index=leg.index,
        mode=leg.mode,
        from_node_id=leg.from_node_id,
        to_node_id=leg.to_node_id,
        edge_id=leg.edge_id,
        edge_kind=leg.edge_kind,
        from_ref=leg.from_ref,
        to_ref=leg.to_ref,
        from_name=leg.from_name,
        to_name=leg.to_name,
        route_id=leg.route_id,
        provider=leg.provider,
        distance_meters=dist,
        is_transfer=leg.is_transfer,
        needs_enrichment=False,
        estimated_departure=leg.estimated_departure,
        estimated_arrival=leg.estimated_arrival,
        waiting_seconds=leg.waiting_seconds,
        segment_role=leg.segment_role,
        cost_inr=leg.cost_inr,
        cost_status=leg.cost_status,
        duration_seconds=dur_s,
        duration_status=ValueStatus.KNOWN.value
        if dur_s is not None
        else ValueStatus.UNKNOWN.value,
        walking_meters=leg.walking_meters,
        provenance=_maps_provenance(enrichment),
        metadata=meta,
    )
    # Refresh cost (e.g. auto fare from enriched distance); keep Maps duration.
    priced = annotate_leg_economics(updated)
    return JourneyLeg(
        index=priced.index,
        mode=priced.mode,
        from_node_id=priced.from_node_id,
        to_node_id=priced.to_node_id,
        edge_id=priced.edge_id,
        edge_kind=priced.edge_kind,
        from_ref=priced.from_ref,
        to_ref=priced.to_ref,
        from_name=priced.from_name,
        to_name=priced.to_name,
        route_id=priced.route_id,
        provider=priced.provider,
        distance_meters=priced.distance_meters,
        is_transfer=priced.is_transfer,
        needs_enrichment=False,
        estimated_departure=priced.estimated_departure,
        estimated_arrival=priced.estimated_arrival,
        waiting_seconds=priced.waiting_seconds,
        segment_role=priced.segment_role,
        cost_inr=priced.cost_inr,
        cost_status=priced.cost_status,
        duration_seconds=dur_s,
        duration_status=ValueStatus.KNOWN.value
        if dur_s is not None
        else ValueStatus.UNKNOWN.value,
        walking_meters=priced.walking_meters,
        provenance=_maps_provenance(enrichment),
        metadata=priced.metadata,
    )


def apply_traffic_enrichment_to_journey(
    journey: Journey,
    enrichments: List[TrafficEnrichmentResult],
) -> Journey:
    """
    Merge per-leg traffic results into the journey and re-aggregate totals.

    Failed enrichments do not become duration/cost 0.
    """
    by_leg = {e.leg_index: e for e in enrichments}
    new_legs: List[JourneyLeg] = []
    for leg in journey.legs:
        if leg.index in by_leg:
            new_legs.append(apply_leg_enrichment(leg, by_leg[leg.index]))
        else:
            new_legs.append(leg)

    econ = aggregate_journey_economics(new_legs)
    warnings = list(journey.warnings)
    if econ["cost_status"] == ValueStatus.UNKNOWN.value:
        if "JOURNEY_COST_UNKNOWN (partial or missing fares)" not in warnings:
            warnings.append("JOURNEY_COST_UNKNOWN (partial or missing fares)")
    if econ["duration_status"] != ValueStatus.KNOWN.value:
        tag = "JOURNEY_DURATION_UNKNOWN_OR_UNAVAILABLE"
        if tag not in warnings:
            warnings.append(tag)

    updated = Journey(
        candidate_id=journey.candidate_id,
        origin=journey.origin,
        destination=journey.destination,
        legs=new_legs,
        transfer_count=journey.transfer_count,
        walking_distance_meters=econ["walking_distance_meters"],
        transit_leg_count=journey.transit_leg_count,
        road_leg_count=journey.road_leg_count,
        modes=journey.modes,
        snapshot_versions=journey.snapshot_versions,
        provenance_sources=sorted(
            set(journey.provenance_sources)
            | {
                str((e.provenance or {}).get("source"))
                for e in enrichments
                if e.available and e.provenance
            }
        ),
        enrichment_requirements=journey.enrichment_requirements,
        temporal_feasibility=journey.temporal_feasibility
        if econ["duration_status"] != ValueStatus.KNOWN.value
        else "known",
        warnings=warnings,
        total_cost_inr=econ["total_cost_inr"],
        cost_status=econ["cost_status"],
        total_duration_seconds=econ["total_duration_seconds"],
        duration_status=econ["duration_status"],
        access_walking_meters=econ["access_walking_meters"],
        transfer_walking_meters=econ["transfer_walking_meters"],
        egress_walking_meters=econ["egress_walking_meters"],
        mode_signature=journey.mode_signature,
    )
    # Phase 7K-9: Maps may confirm zero-length road egress — drop it.
    from src.journey_builder.normalize import apply_leg_normalization_to_journey

    return apply_leg_normalization_to_journey(updated)


def apply_enrichments(
    journeys: List[Journey],
    enrichment_map: Dict[str, List[TrafficEnrichmentResult]],
) -> List[Journey]:
    out: List[Journey] = []
    for j in journeys:
        results = enrichment_map.get(j.candidate_id) or []
        if results:
            out.append(apply_traffic_enrichment_to_journey(j, results))
        else:
            out.append(j)
    return out
