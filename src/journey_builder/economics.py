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
        if is_only:
            return SegmentRole.FULL_JOURNEY_ROAD
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


def annotate_leg_economics(
    leg: JourneyLeg,
    *,
    fare_rules: Optional[List[Any]] = None,
) -> JourneyLeg:
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
        from src.network.transit_fares import lookup_transit_fare_inr

        stations_travelled = None
        raw_st = (leg.metadata or {}).get("stations_travelled")
        if raw_st is not None:
            try:
                stations_travelled = int(raw_st)
            except (TypeError, ValueError):
                stations_travelled = None

        cost, cost_status, cost_meta = lookup_transit_fare_inr(
            mode=leg.mode,
            from_station_id=leg.from_ref,
            to_station_id=leg.to_ref,
            route_id=leg.route_id,
            fare_rules=fare_rules,
            stations_travelled=stations_travelled,
        )

    duration: Optional[float] = None
    duration_status = ValueStatus.UNKNOWN.value
    duration_meta: Dict[str, Any] = {}
    dist = float(leg.distance_meters or 0.0)
    if leg.mode == MobilityMode.WALK and dist > 0:
        duration = dist / WALK_M_PER_S
        duration_status = ValueStatus.KNOWN.value
        duration_meta = {"duration_kind": "walk_geometry"}
    elif leg.needs_enrichment:
        duration = None
        duration_status = ValueStatus.UNKNOWN.value  # await Maps enrichment
        duration_meta = {"duration_kind": "awaiting_road_enrichment"}
    elif leg.mode == MobilityMode.BUS and dist > 0:
        duration = dist / BUS_M_PER_S
        duration_status = ValueStatus.UNKNOWN.value  # structural estimate only
        duration_meta = {
            "duration_kind": "structural_speed_estimate",
            "speed_m_per_s": BUS_M_PER_S,
            "note": "Not timetable-derived; status remains unknown.",
        }
    elif leg.mode == MobilityMode.METRO and dist > 0:
        duration = dist / METRO_M_PER_S
        duration_status = ValueStatus.UNKNOWN.value
        duration_meta = {
            "duration_kind": "structural_speed_estimate",
            "speed_m_per_s": METRO_M_PER_S,
            "distance_basis": "station_coordinate_haversine",
            "note": (
                "No authoritative BMRCL timetable in published snapshot. "
                "Haversine hop distance × structural metro speed; not known."
            ),
        }
    elif leg.mode in {MobilityMode.AUTO_RICKSHAW, MobilityMode.CAB} and dist > 0:
        # Haversine/placeholder speed until enrichment; still unknown traffic time.
        duration = dist / (400.0 / 60.0)
        duration_status = ValueStatus.UNKNOWN.value
        duration_meta = {"duration_kind": "structural_speed_estimate_pre_enrichment"}

    meta = dict(leg.metadata)
    if cost_meta:
        meta["cost_meta"] = cost_meta
    if duration_meta:
        meta["duration_meta"] = duration_meta

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
        cost_inr=cost,
        cost_status=cost_status,
        duration_seconds=duration,
        duration_status=duration_status,
        walking_meters=walk_m,
        provenance=leg.provenance,
        metadata=meta,
    )


def _is_bmrcl_paid_area_connector(leg: JourneyLeg) -> bool:
    """Walk/interchange inside paid metro area between BMRCL metro segments."""
    if leg.mode != MobilityMode.WALK:
        return False
    if leg.edge_kind in {EdgeKind.INTERCHANGE, EdgeKind.TRANSFER_WALK}:
        return True
    if leg.is_transfer or leg.segment_role == SegmentRole.TRANSFER:
        return True
    meta = leg.metadata or {}
    return bool(meta.get("interchange"))


def reconcile_bmrcl_journey_fares(
    legs: List[JourneyLeg],
    *,
    fare_rules: Optional[List[Any]] = None,
) -> List[JourneyLeg]:
    """
    One continuous BMRCL paid ride → one token fare (no per-segment double count).

    Metro legs separated only by paid-area interchange/transfer walk share one
    fare based on summed stations_travelled. Metro legs separated by bus/road
    are separate tickets.
    """
    if not legs:
        return legs

    from src.network.transit_fares import fare_for_stations_travelled, select_bmrcl_token_fare_rule

    rule = select_bmrcl_token_fare_rule(fare_rules)
    out = list(legs)
    i = 0
    while i < len(out):
        leg = out[i]
        if leg.mode != MobilityMode.METRO:
            i += 1
            continue
        if leg.provider and str(leg.provider).upper() not in {"BMRCL"}:
            i += 1
            continue

        span_metro_idx: List[int] = [i]
        j = i + 1
        while j < len(out):
            nxt = out[j]
            if nxt.mode == MobilityMode.METRO:
                span_metro_idx.append(j)
                j += 1
                continue
            if (
                _is_bmrcl_paid_area_connector(nxt)
                and j + 1 < len(out)
                and out[j + 1].mode == MobilityMode.METRO
            ):
                j += 1
                continue
            break

        if len(span_metro_idx) == 1 and rule is None:
            i = span_metro_idx[-1] + 1
            continue

        stations_total = 0
        missing = False
        for idx in span_metro_idx:
            raw = (out[idx].metadata or {}).get("stations_travelled")
            if raw is None:
                missing = True
                break
            try:
                stations_total += int(raw)
            except (TypeError, ValueError):
                missing = True
                break

        if missing or rule is None:
            # Keep per-leg annotate results (unknown if no hop count).
            i = span_metro_idx[-1] + 1
            continue

        amount, status, fare_meta = fare_for_stations_travelled(
            stations_total, rule=rule
        )
        fare_meta = dict(fare_meta)
        fare_meta["bmrcl_paid_span_metro_legs"] = list(span_metro_idx)
        fare_meta["stations_travelled_span_total"] = stations_total

        for k, idx in enumerate(span_metro_idx):
            old = out[idx]
            meta = dict(old.metadata or {})
            if k == 0:
                meta["cost_meta"] = fare_meta
                out[idx] = JourneyLeg(
                    index=old.index,
                    mode=old.mode,
                    from_node_id=old.from_node_id,
                    to_node_id=old.to_node_id,
                    edge_id=old.edge_id,
                    edge_kind=old.edge_kind,
                    from_ref=old.from_ref,
                    to_ref=old.to_ref,
                    from_name=old.from_name,
                    to_name=old.to_name,
                    route_id=old.route_id,
                    provider=old.provider,
                    distance_meters=old.distance_meters,
                    is_transfer=old.is_transfer,
                    needs_enrichment=old.needs_enrichment,
                    estimated_departure=old.estimated_departure,
                    estimated_arrival=old.estimated_arrival,
                    waiting_seconds=old.waiting_seconds,
                    segment_role=old.segment_role,
                    cost_inr=amount,
                    cost_status=status,
                    duration_seconds=old.duration_seconds,
                    duration_status=old.duration_status,
                    walking_meters=old.walking_meters,
                    provenance=old.provenance,
                    metadata=meta,
                )
            else:
                meta["cost_meta"] = {
                    "fare_kind": "bmrcl_fare_included_in_prior_metro_leg",
                    "included_in_leg_index": span_metro_idx[0],
                    "stations_travelled_this_leg": (old.metadata or {}).get(
                        "stations_travelled"
                    ),
                }
                out[idx] = JourneyLeg(
                    index=old.index,
                    mode=old.mode,
                    from_node_id=old.from_node_id,
                    to_node_id=old.to_node_id,
                    edge_id=old.edge_id,
                    edge_kind=old.edge_kind,
                    from_ref=old.from_ref,
                    to_ref=old.to_ref,
                    from_name=old.from_name,
                    to_name=old.to_name,
                    route_id=old.route_id,
                    provider=old.provider,
                    distance_meters=old.distance_meters,
                    is_transfer=old.is_transfer,
                    needs_enrichment=old.needs_enrichment,
                    estimated_departure=old.estimated_departure,
                    estimated_arrival=old.estimated_arrival,
                    waiting_seconds=old.waiting_seconds,
                    segment_role=old.segment_role,
                    cost_inr=0.0,
                    cost_status=ValueStatus.KNOWN.value,
                    duration_seconds=old.duration_seconds,
                    duration_status=old.duration_status,
                    walking_meters=old.walking_meters,
                    provenance=old.provenance,
                    metadata=meta,
                )

        i = span_metro_idx[-1] + 1

    return out


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
