"""
Phase 7K-9 — drop zero-movement access/egress / self-transfer legs.

Identity via node id / published stop-or-station ref. Distance (and optional
coordinates) only when a leg does not change network location.
Does not change ranking weights.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from src.journey_builder.graph import haversine_m
from src.journey_builder.models import (
    EdgeKind,
    EnrichmentRequirement,
    Journey,
    JourneyLeg,
)
from src.journey_builder.economics import (
    aggregate_journey_economics,
    infer_segment_role,
    mode_signature,
    reconcile_bmrcl_journey_fares,
)
from src.network.models import MobilityMode

# Match overlay skip of sub-meter direct OD; float-safe.
_NULL_MOVE_M = 1.0

_ROAD_OR_WALK = frozenset(
    {
        MobilityMode.WALK,
        MobilityMode.AUTO_RICKSHAW,
        MobilityMode.CAB,
    }
)
_TRANSIT = frozenset({MobilityMode.METRO, MobilityMode.BUS})

NodeCoords = Mapping[str, Tuple[float, float]]


def _mode(leg: JourneyLeg) -> MobilityMode:
    m = leg.mode
    if isinstance(m, MobilityMode):
        return m
    try:
        return MobilityMode(str(m))
    except Exception:  # noqa: BLE001
        return MobilityMode.WALK


def _kind_and_ref(
    node_id: Optional[str], ref: Optional[str]
) -> Optional[Tuple[str, str]]:
    """Stable published identity: ('station'|'stop', id). No name matching."""
    if ref:
        rid = str(ref)
        nid = str(node_id or "")
        if nid.startswith("station:"):
            return ("station", rid)
        if nid.startswith("stop:"):
            return ("stop", rid)
        if nid.startswith("access:"):
            return None
        return ("ref", rid)
    if not node_id:
        return None
    nid = str(node_id)
    if nid.startswith("station:"):
        return ("station", nid[len("station:") :])
    if nid.startswith("stop:"):
        return ("stop", nid[len("stop:") :])
    return None


def same_network_location(
    a_id: Optional[str],
    a_ref: Optional[str],
    b_id: Optional[str],
    b_ref: Optional[str],
) -> bool:
    if a_id and b_id and a_id == b_id:
        return True
    a = _kind_and_ref(a_id, a_ref)
    b = _kind_and_ref(b_id, b_ref)
    return a is not None and a == b


def _coord_distance_m(
    leg: JourneyLeg, node_coords: Optional[NodeCoords]
) -> Optional[float]:
    if not node_coords:
        return None
    a = node_coords.get(leg.from_node_id)
    b = node_coords.get(leg.to_node_id)
    if a is None or b is None:
        return None
    return haversine_m(a[0], a[1], b[0], b[1])


def is_null_movement_leg(
    leg: JourneyLeg,
    *,
    coord_distance_m: Optional[float] = None,
) -> bool:
    """
    True when a leg does not change physical network location.

    - same node id
    - same published station/stop identity
    - walk/auto/cab with distance (or coordinate fallback) <= 1 m
    """
    if same_network_location(
        leg.from_node_id, leg.from_ref, leg.to_node_id, leg.to_ref
    ):
        return True

    mode = _mode(leg)
    if mode not in _ROAD_OR_WALK:
        return False

    distances: List[float] = []
    if leg.distance_meters is not None:
        try:
            distances.append(float(leg.distance_meters))
        except (TypeError, ValueError):
            pass
    if coord_distance_m is not None:
        try:
            distances.append(float(coord_distance_m))
        except (TypeError, ValueError):
            pass
    if not distances:
        return False
    return min(distances) <= _NULL_MOVE_M


def is_self_connector_after_transit(
    prev: Optional[JourneyLeg],
    leg: JourneyLeg,
    *,
    coord_distance_m: Optional[float] = None,
) -> bool:
    """
    transit → walk/auto/cab that ends at the same node just alighted,
    with no meaningful movement.
    """
    if is_null_movement_leg(leg, coord_distance_m=coord_distance_m):
        return True
    if prev is None or _mode(prev) not in _TRANSIT:
        return False
    if _mode(leg) not in _ROAD_OR_WALK:
        return False
    # Already at prev.to; this leg's endpoints are that same node.
    alight_id, alight_ref = prev.to_node_id, prev.to_ref
    from_same = same_network_location(
        leg.from_node_id, leg.from_ref, alight_id, alight_ref
    )
    to_same = same_network_location(
        leg.to_node_id, leg.to_ref, alight_id, alight_ref
    )
    if from_same and to_same:
        return True
    return False


def collapse_null_movement_legs(
    legs: List[JourneyLeg],
    *,
    node_coords: Optional[NodeCoords] = None,
) -> List[JourneyLeg]:
    """Remove null-movement legs and reindex. Empty input unchanged."""
    if not legs:
        return legs
    kept: List[JourneyLeg] = []
    prev_kept: Optional[JourneyLeg] = None
    for leg in legs:
        cd = _coord_distance_m(leg, node_coords)
        if is_self_connector_after_transit(
            prev_kept, leg, coord_distance_m=cd
        ):
            continue
        kept.append(leg)
        prev_kept = leg
    if len(kept) == len(legs):
        return legs
    return [replace(leg, index=i) for i, leg in enumerate(kept)]


def merge_adjacent_same_route_transit(legs: List[JourneyLeg]) -> List[JourneyLeg]:
    """Merge consecutive same-route bus/metro legs split by a removed dummy connector."""
    if len(legs) < 2:
        return legs
    out: List[JourneyLeg] = [legs[0]]
    changed = False
    for nxt in legs[1:]:
        cur = out[-1]
        same = (
            _mode(cur) in _TRANSIT
            and _mode(cur) == _mode(nxt)
            and cur.route_id
            and nxt.route_id
            and cur.route_id == nxt.route_id
            and cur.to_node_id == nxt.from_node_id
        )
        if not same:
            out.append(nxt)
            continue
        changed = True
        dist = None
        if cur.distance_meters is not None and nxt.distance_meters is not None:
            dist = float(cur.distance_meters) + float(nxt.distance_meters)
        dur = None
        if cur.duration_seconds is not None and nxt.duration_seconds is not None:
            dur = float(cur.duration_seconds) + float(nxt.duration_seconds)
        meta = dict(cur.metadata or {})
        nxt_meta = nxt.metadata or {}
        cur_st = meta.get("stations_travelled")
        nxt_st = nxt_meta.get("stations_travelled")
        if cur_st is not None and nxt_st is not None:
            try:
                meta["stations_travelled"] = int(cur_st) + int(nxt_st)
            except (TypeError, ValueError):
                pass
        cost = cur.cost_inr
        cost_status = cur.cost_status
        out[-1] = replace(
            cur,
            to_node_id=nxt.to_node_id,
            to_ref=nxt.to_ref,
            to_name=nxt.to_name,
            edge_id=f"{cur.edge_id}+{nxt.to_node_id}",
            distance_meters=dist if dist is not None else cur.distance_meters,
            duration_seconds=dur if dur is not None else cur.duration_seconds,
            cost_inr=cost,
            cost_status=cost_status,
            is_transfer=cur.is_transfer,
            metadata=meta,
        )
    if not changed:
        return legs
    return [replace(leg, index=i) for i, leg in enumerate(out)]


def recompute_transfer_flags(legs: List[JourneyLeg]) -> List[JourneyLeg]:
    last_transit_route: Optional[str] = None
    out: List[JourneyLeg] = []
    for i, leg in enumerate(legs):
        is_transfer = False
        kind = leg.edge_kind
        if kind in {EdgeKind.BUS, EdgeKind.METRO}:
            if (
                last_transit_route is not None
                and leg.route_id
                and leg.route_id != last_transit_route
            ):
                is_transfer = True
            if leg.route_id:
                last_transit_route = leg.route_id
        if kind == EdgeKind.INTERCHANGE:
            is_transfer = True
        out.append(replace(leg, index=i, is_transfer=is_transfer))
    return out


def reinfer_segment_roles(legs: List[JourneyLeg]) -> List[JourneyLeg]:
    n = len(legs)
    if n == 0:
        return legs
    out: List[JourneyLeg] = []
    for i, leg in enumerate(legs):
        role = infer_segment_role(
            leg.edge_kind,
            from_node_id=leg.from_node_id,
            to_node_id=leg.to_node_id,
            is_first=(i == 0),
            is_last=(i == n - 1),
            is_only=(n == 1),
        )
        out.append(replace(leg, index=i, segment_role=role))
    return out


def normalize_journey_legs(
    legs: List[JourneyLeg],
    *,
    node_coords: Optional[NodeCoords] = None,
) -> List[JourneyLeg]:
    """Collapse null-movement legs then merge split same-route transit."""
    collapsed = collapse_null_movement_legs(legs, node_coords=node_coords)
    merged = merge_adjacent_same_route_transit(collapsed)
    flagged = recompute_transfer_flags(merged)
    return reinfer_segment_roles(flagged)


def rebuild_enrichments_for_legs(
    legs: Sequence[JourneyLeg],
    *,
    node_coords: Optional[NodeCoords] = None,
    previous: Optional[Sequence[EnrichmentRequirement]] = None,
) -> List[EnrichmentRequirement]:
    prev_by_old: Dict[int, EnrichmentRequirement] = {}
    if previous:
        for e in previous:
            prev_by_old[e.leg_index] = e
    out: List[EnrichmentRequirement] = []
    coords = node_coords or {}
    for i, leg in enumerate(legs):
        if not leg.needs_enrichment:
            continue
        prev = prev_by_old.get(leg.index)
        fla, flo = coords.get(leg.from_node_id, (None, None))
        tla, tlo = coords.get(leg.to_node_id, (None, None))
        if prev is not None:
            out.append(replace(prev, leg_index=i))
        else:
            out.append(
                EnrichmentRequirement(
                    requirement_type="road_geometry_time",
                    leg_index=i,
                    mode=leg.mode.value,
                    from_lat=fla,
                    from_lon=flo,
                    to_lat=tla,
                    to_lon=tlo,
                    notes="Resolve via live routing layer; not fabricated here.",
                )
            )
    return out


def apply_leg_normalization_to_journey(
    journey: Journey,
    *,
    fare_rules: Optional[List] = None,
    node_coords: Optional[NodeCoords] = None,
) -> Journey:
    """Normalize legs and re-aggregate. No-op when structure is unchanged."""
    old = list(journey.legs)
    new_legs = normalize_journey_legs(old, node_coords=node_coords)

    def _key(leg: JourneyLeg) -> Tuple:
        return (
            leg.mode.value if hasattr(leg.mode, "value") else str(leg.mode),
            leg.from_node_id,
            leg.to_node_id,
            leg.route_id,
            round(float(leg.distance_meters), 2)
            if leg.distance_meters is not None
            else None,
            bool(leg.is_transfer),
        )

    if [_key(l) for l in new_legs] == [_key(l) for l in old]:
        return journey
    new_legs = reconcile_bmrcl_journey_fares(new_legs, fare_rules=fare_rules)
    econ = aggregate_journey_economics(new_legs)
    modes = [leg.mode.value for leg in new_legs]
    transit_legs = sum(
        1 for leg in new_legs if leg.edge_kind in {EdgeKind.BUS, EdgeKind.METRO}
    )
    road_legs = sum(
        1
        for leg in new_legs
        if leg.edge_kind in {EdgeKind.ROAD_ACCESS, EdgeKind.ROAD_DIRECT}
    )
    transfers = sum(1 for leg in new_legs if leg.is_transfer)
    enrichments = rebuild_enrichments_for_legs(
        new_legs,
        node_coords=node_coords,
    )
    return Journey(
        candidate_id=journey.candidate_id,
        origin=journey.origin,
        destination=journey.destination,
        legs=new_legs,
        transfer_count=transfers,
        walking_distance_meters=econ["walking_distance_meters"],
        transit_leg_count=transit_legs,
        road_leg_count=road_legs,
        modes=modes,
        snapshot_versions=journey.snapshot_versions,
        provenance_sources=list(journey.provenance_sources),
        enrichment_requirements=enrichments,
        temporal_feasibility=journey.temporal_feasibility,
        warnings=list(journey.warnings),
        total_cost_inr=econ["total_cost_inr"],
        cost_status=econ["cost_status"],
        total_duration_seconds=econ["total_duration_seconds"],
        duration_status=econ["duration_status"],
        access_walking_meters=econ["access_walking_meters"],
        transfer_walking_meters=econ["transfer_walking_meters"],
        egress_walking_meters=econ["egress_walking_meters"],
        mode_signature=mode_signature(new_legs),
    )
