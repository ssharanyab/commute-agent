"""
Journey-level cost / duration / walking aggregation (Phase 6D).

Does not invent live cab fares. Regulated auto fare is an estimate with provenance.
Does not redesign Decision Engine scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.journey_builder.models import (
    EdgeKind,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
)
from src.network.models import MobilityMode


WALK_M_PER_S = 80.0 / 60.0  # ~1.333 m/s
BUS_M_PER_S = 250.0 / 60.0
METRO_M_PER_S = 500.0 / 60.0


def infer_segment_role(
    edge_kind: EdgeKind,
    *,
    from_node_id: str,
    to_node_id: str,
    is_first: bool,
    is_last: bool,
    is_only: bool,
) -> SegmentRole:
    if edge_kind == EdgeKind.ROAD_DIRECT:
        return SegmentRole.FULL_JOURNEY_ROAD
    if edge_kind in {EdgeKind.BUS, EdgeKind.METRO}:
        return SegmentRole.TRANSIT
    if edge_kind == EdgeKind.TRANSFER_WALK or edge_kind == EdgeKind.INTERCHANGE:
        return SegmentRole.TRANSFER
    if edge_kind == EdgeKind.ROAD_ACCESS:
        if is_only:
            return SegmentRole.FULL_JOURNEY_ROAD
        if from_node_id.startswith("access:origin") or is_first:
            return SegmentRole.ACCESS
        if to_node_id.startswith("access:destination") or is_last:
            return SegmentRole.EGRESS
        return SegmentRole.TRANSFER
    if edge_kind == EdgeKind.WALK:
        if is_only and from_node_id.startswith("access:origin"):
            return SegmentRole.FULL_JOURNEY_ROAD  # walk-only OD
        if from_node_id.startswith("access:origin") or (
            is_first and not to_node_id.startswith("access:destination")
        ):
            return SegmentRole.ACCESS
        if to_node_id.startswith("access:destination") or is_last:
            return SegmentRole.EGRESS
        return SegmentRole.TRANSFER
    return SegmentRole.OTHER


def mode_signature(legs: List[JourneyLeg]) -> str:
    parts: List[str] = []
    for leg in legs:
        token = leg.mode.value
        if token == "auto_rickshaw":
            token = "auto"
        parts.append(token)
    # Collapse consecutive identical tokens for audit readability only.
    collapsed: List[str] = []
    for p in parts:
        if not collapsed or collapsed[-1] != p:
            collapsed.append(p)
    return " → ".join(collapsed)


def _auto_fare_estimate_inr(distance_meters: Optional[float]) -> Tuple[Optional[float], str, Dict[str, Any]]:
    if distance_meters is None or distance_meters < 0:
        return None, ValueStatus.UNKNOWN.value, {"reason": "missing_distance"}
    try:
        from src.network.ingest.fares import build_auto_fare_rule, compute_auto_fare_inr

        rule = build_auto_fare_rule()
        fare = compute_auto_fare_inr(rule, distance_km=float(distance_meters) / 1000.0)
        return (
            fare,
            ValueStatus.KNOWN.value,
            {
                "fare_kind": "government_regulated_estimate",
                "rule_id": rule.id,
                "not_live_aggregator": True,
                "provenance_source": rule.provenance.source,
                "provenance_source_type": rule.provenance.source_type.value,
            },
        )
    except Exception as exc:
        return None, ValueStatus.UNKNOWN.value, {"reason": f"auto_fare_error:{type(exc).__name__}"}


def annotate_leg_economics(leg: JourneyLeg) -> JourneyLeg:
    """Fill cost/duration/walking fields on a single leg (immutable → replace)."""
    walk_m = 0.0
    if leg.mode == MobilityMode.WALK:
        walk_m = float(leg.distance_meters or 0.0)

    cost: Optional[float] = None
    cost_status = ValueStatus.UNKNOWN.value
    cost_meta: Dict[str, Any] = {}

    if leg.mode == MobilityMode.WALK:
        cost = 0.0
        cost_status = ValueStatus.KNOWN.value
        cost_meta = {"fare_kind": "walk_zero"}
    elif leg.mode == MobilityMode.AUTO_RICKSHAW:
        cost, cost_status, cost_meta = _auto_fare_estimate_inr(leg.distance_meters)
    elif leg.mode == MobilityMode.CAB:
        cost = None
        cost_status = ValueStatus.UNKNOWN.value
        cost_meta = {
            "fare_kind": "cab_fare_not_configured",
            "note": "No live cab-price provider; cost remains unknown (not fabricated).",
        }
    elif leg.mode in {MobilityMode.BUS, MobilityMode.METRO}:
        cost = None
        cost_status = ValueStatus.UNKNOWN.value
        cost_meta = {"fare_kind": "transit_fare_not_applied_in_builder"}

    duration: Optional[float] = None
    duration_status = ValueStatus.UNKNOWN.value
    dist = float(leg.distance_meters or 0.0)
    if leg.mode == MobilityMode.WALK and dist > 0:
        duration = dist / WALK_M_PER_S
        duration_status = ValueStatus.KNOWN.value
    elif leg.needs_enrichment:
        duration = None
        duration_status = ValueStatus.UNKNOWN.value  # await Maps enrichment
    elif leg.mode == MobilityMode.BUS and dist > 0:
        duration = dist / BUS_M_PER_S
        duration_status = ValueStatus.UNKNOWN.value  # structural estimate only
    elif leg.mode == MobilityMode.METRO and dist > 0:
        duration = dist / METRO_M_PER_S
        duration_status = ValueStatus.UNKNOWN.value
    elif leg.mode in {MobilityMode.AUTO_RICKSHAW, MobilityMode.CAB} and dist > 0:
        # Haversine/placeholder speed until enrichment; still unknown traffic time.
        duration = dist / (400.0 / 60.0)
        duration_status = ValueStatus.UNKNOWN.value

    meta = dict(leg.metadata)
    if cost_meta:
        meta["cost_meta"] = cost_meta

    return JourneyLeg(
        index=leg.index,
        mode=leg.mode,
        from_node_id=leg.from_node_id,
        to_node_id=leg.to_node_id,
        edge_id=leg.edge_id,
        edge_kind=leg.edge_kind,
        from_ref=leg.from_ref,
        to_ref=leg.to_ref,
        route_id=leg.route_id,
        provider=leg.provider,
        distance_meters=leg.distance_meters,
        is_transfer=leg.is_transfer,
        needs_enrichment=leg.needs_enrichment,
        estimated_departure=leg.estimated_departure,
        estimated_arrival=leg.estimated_arrival,
        waiting_seconds=leg.waiting_seconds,
        segment_role=leg.segment_role,
        cost_inr=cost,
        cost_status=cost_status,
        duration_seconds=duration,
        duration_status=duration_status,
        walking_meters=walk_m,
        provenance=leg.provenance,
        metadata=meta,
    )


def aggregate_journey_economics(
    legs: List[JourneyLeg],
) -> Dict[str, Any]:
    access_w = sum(
        l.walking_meters for l in legs if l.segment_role == SegmentRole.ACCESS
    )
    transfer_w = sum(
        l.walking_meters for l in legs if l.segment_role == SegmentRole.TRANSFER
    )
    egress_w = sum(
        l.walking_meters for l in legs if l.segment_role == SegmentRole.EGRESS
    )
    full_w = sum(
        l.walking_meters
        for l in legs
        if l.segment_role == SegmentRole.FULL_JOURNEY_ROAD
    )
    total_walk = sum(l.walking_meters for l in legs)
    partial_cost = round(
        sum(float(l.cost_inr) for l in legs if l.cost_inr is not None), 2
    )

    if any(l.cost_status == ValueStatus.UNAVAILABLE.value for l in legs):
        total_cost = None
        cost_status = ValueStatus.UNAVAILABLE.value
    elif all(l.cost_status == ValueStatus.KNOWN.value for l in legs):
        total_cost = partial_cost
        cost_status = ValueStatus.KNOWN.value
    else:
        total_cost = None
        cost_status = ValueStatus.UNKNOWN.value

    if all(l.duration_status == ValueStatus.KNOWN.value for l in legs):
        total_dur: Optional[float] = sum(
            float(l.duration_seconds or 0.0) for l in legs
        )
        dur_status = ValueStatus.KNOWN.value
    else:
        total_dur = None
        dur_status = ValueStatus.UNKNOWN.value

    return {
        "access_walking_meters": round(access_w, 2),
        "transfer_walking_meters": round(transfer_w, 2),
        "egress_walking_meters": round(egress_w, 2),
        "full_journey_walking_meters": round(full_w, 2),
        "walking_distance_meters": round(total_walk, 2),
        "total_cost_inr": total_cost,
        "cost_status": cost_status,
        "total_duration_seconds": total_dur,
        "duration_status": dur_status,
        "partial_known_cost_sum_inr": partial_cost,
    }
