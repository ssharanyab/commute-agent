"""
Dynamic multimodal Journey Builder — bounded deterministic graph search.

Paths are discovered from MobilityNetworkGraph topology only.
No journey-template constants. No live Maps / LLM calls.

Phase 6B search:
  Goal-directed A* with route-continuation expansion.
  Consecutive same-route stop hops count as one logical transit leg
  (matching post-search ``_compress_edges`` semantics).
"""

from __future__ import annotations

import hashlib
import heapq
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from src.journey_builder.constraints import JourneyConstraints, SearchLimits
from src.journey_builder.diversity import (
    collapse_mode_tokens,
    select_diverse_journeys,
    select_diverse_partials,
    transit_pattern,
)
from src.journey_builder.economics import (
    aggregate_journey_economics,
    annotate_leg_economics,
    infer_segment_role,
    mode_signature,
)
from src.journey_builder.graph import (
    MobilityNetworkGraph,
    build_mobility_graph,
    haversine_m,
)
from src.journey_builder.models import (
    EdgeKind,
    EnrichmentRequirement,
    GraphEdge,
    GraphNode,
    Journey,
    JourneyBuildRequest,
    JourneyBuildResult,
    JourneyLeg,
    NodeKind,
    SegmentRole,
)
from src.network.models import MobilityMode, SourceType, DataProvenance
from src.network.repository import StaticMobilityDataRepository


ORIGIN_ID = "access:origin"
DEST_ID = "access:destination"

# Search-ordering only (meters-equivalent). NOT Decision Engine utility.
_TRANSFER_COST_M = 2500.0
_LEG_COST_M = 50.0

_TRANSIT_KINDS = {EdgeKind.BUS, EdgeKind.METRO}
_ALGORITHM = "astar_route_continuation"

# Collection: allow many destination reaches so rarer structural classes
# (e.g. bus→metro) can appear after near-duplicate bus-only paths.
# Retention still capped at max_candidates via diversity selection.
# Hard mult calibrated on EC→Majestic road_on audit (metro ~dest_reach 1100).
_COLLECTION_SOFT_MULT = 3
_COLLECTION_HARD_MULT = 60
_PER_SIGNATURE_CAP = 3


def _access_family(modes: Tuple[str, ...]) -> Optional[str]:
    """Collapse cab/auto for intermediate dominance; keep walk distinct."""
    if not modes:
        return None
    m = modes[0]
    if m in {"cab", "auto_rickshaw", "auto"}:
        return "road"
    return m


@dataclass(frozen=True)
class _Partial:
    node_id: str
    edge_ids: Tuple[str, ...]
    transfers: int
    walking_m: float
    last_transit_route: Optional[str]
    legs: int
    # Mode sequence (logical legs) — used for DEST dominance + diversity.
    modes: Tuple[str, ...] = ()

    @property
    def dominance_key(self) -> Tuple[Any, ...]:
        # Intermediate: (node, route, access_family) — collapse cab vs auto on
        # the same boarding, but do not let road prune walk (or vice versa).
        # Destination: full modes so road-direct variants stay distinct.
        if self.node_id == DEST_ID:
            return (self.node_id, self.last_transit_route, self.modes)
        return (
            self.node_id,
            self.last_transit_route,
            _access_family(self.modes),
        )


def _access_prov(note: str, at: datetime) -> DataProvenance:
    return DataProvenance(
        source="journey_builder_access",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=at,
        notes=note,
    )


def _mode_from_token(token: str) -> MobilityMode:
    mapping = {
        "walk": MobilityMode.WALK,
        "walking": MobilityMode.WALK,
        "bus": MobilityMode.BUS,
        "metro": MobilityMode.METRO,
        "cab": MobilityMode.CAB,
        "taxi": MobilityMode.CAB,
        "auto": MobilityMode.AUTO_RICKSHAW,
        "auto_rickshaw": MobilityMode.AUTO_RICKSHAW,
        "rideshare": MobilityMode.CAB,
    }
    return mapping.get(token.lower(), MobilityMode.WALK)


def _heuristic_m(
    graph: MobilityNetworkGraph,
    node_id: str,
    dest_lat: float,
    dest_lon: float,
) -> float:
    """
    Admissible geographic heuristic: haversine to destination.

    Missing coordinates → 0 (never overestimates remaining distance).
    """
    if node_id == DEST_ID:
        return 0.0
    node = graph.nodes.get(node_id)
    if node is None or node.latitude is None or node.longitude is None:
        return 0.0
    return haversine_m(node.latitude, node.longitude, dest_lat, dest_lon)


def _g_cost(state: _Partial) -> float:
    """Structural search cost (ordering only — not user preference scoring)."""
    return (
        state.walking_m
        + state.transfers * _TRANSFER_COST_M
        + state.legs * _LEG_COST_M
    )


def _alightings_along_route(
    graph: MobilityNetworkGraph,
    start_node: str,
    route_id: str,
) -> List[Tuple[str, Tuple[str, ...], float]]:
    """
    All downstream nodes reachable from ``start_node`` following only edges
    of ``route_id``. Each hop is recorded; caller treats the whole ride as
    one logical leg.
    """
    results: List[Tuple[str, Tuple[str, ...], float]] = []
    # Stack of (current_node, edge_ids_so_far, dist_so_far)
    stack: List[Tuple[str, Tuple[str, ...], float]] = [(start_node, (), 0.0)]
    used_edges: Set[str] = set()

    while stack:
        cur, eids, dist = stack.pop()
        outgoing = sorted(graph.outgoing(cur), key=lambda e: e.id)
        for edge in outgoing:
            if edge.route_id != route_id:
                continue
            if edge.kind not in _TRANSIT_KINDS:
                continue
            if edge.id in used_edges:
                continue
            used_edges.add(edge.id)
            hop_dist = float(edge.distance_meters or 0.0)
            new_eids = eids + (edge.id,)
            new_dist = dist + hop_dist
            results.append((edge.to_node, new_eids, new_dist))
            stack.append((edge.to_node, new_eids, new_dist))

    return results


def _can_egress_to_dest(graph: MobilityNetworkGraph, node_id: str) -> bool:
    return any(e.to_node == DEST_ID for e in graph.outgoing(node_id))


def _filter_alightings(
    graph: MobilityNetworkGraph,
    from_node: str,
    alightings: List[Tuple[str, Tuple[str, ...], float]],
    dest_lat: float,
    dest_lon: float,
) -> List[Tuple[str, Tuple[str, ...], float]]:
    """
    Keep alightings that make geographic progress or can finish the journey.

    Avoids enqueueing every intermediate stop on long routes (branching),
    while always retaining stops with an egress edge to the destination overlay.
    """
    h_from = _heuristic_m(graph, from_node, dest_lat, dest_lon)
    kept: List[Tuple[str, Tuple[str, ...], float]] = []
    for to_node, eids, dist in alightings:
        if _can_egress_to_dest(graph, to_node):
            kept.append((to_node, eids, dist))
            continue
        h_to = _heuristic_m(graph, to_node, dest_lat, dest_lon)
        # Require strict geographic progress toward the destination.
        if h_to < h_from:
            kept.append((to_node, eids, dist))
    # Deterministic order: closer to dest first, then edge-id path.
    kept.sort(
        key=lambda t: (
            _heuristic_m(graph, t[0], dest_lat, dest_lon),
            t[1],
        )
    )
    return kept


class DynamicJourneyBuilder:
    """
    Compose candidate journeys from a static mobility repository.

    Search: bounded A* with geographic heuristic and route-continuation
    expansion (consecutive same-route hops = one logical leg). Dominance
    at intermediate nodes: (node, last_transit_route). At destination:
    modes included so road-direct variants stay distinct. Destination
    reaches are signature-capped; collection uses a hard multiplier so
    rarer structural classes are not starved by near-duplicates.
    """

    def __init__(
        self,
        repository: StaticMobilityDataRepository,
        *,
        graph: Optional[MobilityNetworkGraph] = None,
        default_limits: Optional[SearchLimits] = None,
    ):
        self.repository = repository
        self._base_graph = graph
        self.default_limits = default_limits or SearchLimits()
        self._last_access_meta: Dict[str, Any] = {}

    def _graph(self, limits: SearchLimits) -> MobilityNetworkGraph:
        if self._base_graph is not None:
            return self._base_graph
        return build_mobility_graph(
            self.repository,
            walk_transfer_meters=limits.max_walk_transfer_meters,
        )

    def build(self, request: JourneyBuildRequest) -> JourneyBuildResult:
        limits: SearchLimits = request.search_limits or self.default_limits
        constraints: JourneyConstraints = (
            request.constraints or JourneyConstraints()
        )
        base = self._graph(limits)
        graph = self._overlay_access(base, request, limits, constraints)

        warnings: List[str] = []
        if not base.nodes:
            warnings.append("EMPTY_NETWORK_GRAPH")

        candidates, meta = self._search(
            graph, request, limits, constraints, warnings
        )

        # Deterministic ordering then structural diversity retention.
        candidates.sort(
            key=lambda j: (
                j.transfer_count,
                len(j.legs),
                j.walking_distance_meters,
                j.candidate_id,
            )
        )
        before_trim = len(candidates)
        candidates, div_meta = select_diverse_journeys(
            candidates,
            max_candidates=limits.max_candidates,
            per_signature=_PER_SIGNATURE_CAP,
        )
        meta["candidates_retained"] = len(candidates)
        meta["candidates_trimmed"] = max(0, before_trim - len(candidates))
        meta["candidate_cap_pruned"] = meta["candidates_trimmed"]
        meta["diversity"] = div_meta

        return JourneyBuildResult(
            candidates=candidates,
            search_metadata={
                **meta,
                "search_limits": limits.to_dict(),
                "graph_stats": graph.stats(),
                "departure_time": request.departure_time.isoformat(),
                "algorithm": _ALGORITHM,
            },
            constraints_applied=constraints.to_dict(),
            network_snapshot_versions=dict(base.snapshot_versions),
            warnings=warnings,
            provenance={
                "builder": "DynamicJourneyBuilder",
                "network_sources": list(base.provenance_notes),
                "snapshot_versions": dict(base.snapshot_versions),
            },
        )

    def _overlay_access(
        self,
        base: MobilityNetworkGraph,
        request: JourneyBuildRequest,
        limits: SearchLimits,
        constraints: JourneyConstraints,
    ) -> MobilityNetworkGraph:
        """Copy graph and attach origin/destination access edges (no fake roads)."""
        g = MobilityNetworkGraph(
            nodes=dict(base.nodes),
            edges=dict(base.edges),
            adjacency={k: list(v) for k, v in base.adjacency.items()},
            snapshot_versions=dict(base.snapshot_versions),
            provenance_notes=list(base.provenance_notes),
        )
        o_lat, o_lon = request.origin
        d_lat, d_lon = request.destination
        access_at = request.departure_time

        g.add_node(
            GraphNode(
                id=ORIGIN_ID,
                kind=NodeKind.ORIGIN,
                name="Origin",
                latitude=o_lat,
                longitude=o_lon,
            )
        )
        g.add_node(
            GraphNode(
                id=DEST_ID,
                kind=NodeKind.DESTINATION,
                name="Destination",
                latitude=d_lat,
                longitude=d_lon,
            )
        )

        # Direct walk if close enough
        direct = haversine_m(o_lat, o_lon, d_lat, d_lon)
        if (
            constraints.mode_allowed(MobilityMode.WALK)
            and direct <= limits.max_direct_walk_meters
        ):
            g.add_edge(
                GraphEdge(
                    id="walk:origin->destination",
                    from_node=ORIGIN_ID,
                    to_node=DEST_ID,
                    kind=EdgeKind.WALK,
                    mode=MobilityMode.WALK,
                    distance_meters=direct,
                    provenance=_access_prov("Direct walk OD", access_at),
                    metadata={"segment_hint": SegmentRole.FULL_JOURNEY_ROAD.value},
                )
            )

        # Full-journey road OD (cab/auto) — geometry/time via enrichment later.
        if (
            getattr(limits, "allow_direct_road", True)
            and limits.allow_road_access
            and direct <= limits.max_direct_road_meters
        ):
            for mode_token in limits.road_access_modes:
                if not constraints.mode_allowed(mode_token):
                    continue
                mode = _mode_from_token(mode_token)
                g.add_edge(
                    GraphEdge(
                        id=f"road:{mode.value}:origin->destination",
                        from_node=ORIGIN_ID,
                        to_node=DEST_ID,
                        kind=EdgeKind.ROAD_DIRECT,
                        mode=mode,
                        distance_meters=direct,
                        needs_enrichment=True,
                        provenance=_access_prov(
                            "Full OD road placeholder; geometry/time via enrichment",
                            access_at,
                        ),
                        metadata={
                            "enrichment": "road_geometry_time",
                            "segment_hint": SegmentRole.FULL_JOURNEY_ROAD.value,
                        },
                    )
                )

        # Collect access/egress candidates, then attach nearest-first within radius.
        access_candidates: List[Tuple[float, GraphNode]] = []
        egress_candidates: List[Tuple[float, GraphNode]] = []
        for node in list(base.nodes.values()):
            if node.latitude is None or node.longitude is None:
                continue
            if node.kind not in {
                NodeKind.BUS_STOP,
                NodeKind.METRO_STATION,
                NodeKind.INTERCHANGE,
            }:
                continue
            d_access = haversine_m(o_lat, o_lon, node.latitude, node.longitude)
            d_egress = haversine_m(d_lat, d_lon, node.latitude, node.longitude)
            if d_access <= max(
                limits.max_walking_access_meters,
                limits.max_road_access_meters if limits.allow_road_access else 0.0,
            ):
                access_candidates.append((d_access, node))
            if d_egress <= max(
                limits.max_walking_egress_meters,
                limits.max_road_access_meters if limits.allow_road_access else 0.0,
            ):
                egress_candidates.append((d_egress, node))

        access_candidates.sort(key=lambda t: (t[0], t[1].id))
        egress_candidates.sort(key=lambda t: (t[0], t[1].id))

        origin_access_ids: List[str] = []
        dest_access_ids: List[str] = []

        for d_access, node in access_candidates:
            linked = False
            if (
                constraints.mode_allowed(MobilityMode.WALK)
                and d_access <= limits.max_walking_access_meters
            ):
                g.add_edge(
                    GraphEdge(
                        id=f"walk:origin->{node.id}",
                        from_node=ORIGIN_ID,
                        to_node=node.id,
                        kind=EdgeKind.WALK,
                        mode=MobilityMode.WALK,
                        distance_meters=d_access,
                        provenance=_access_prov("Walking access", access_at),
                    )
                )
                linked = True
            if limits.allow_road_access and d_access <= limits.max_road_access_meters:
                for mode_token in limits.road_access_modes:
                    if not constraints.mode_allowed(mode_token):
                        continue
                    mode = _mode_from_token(mode_token)
                    g.add_edge(
                        GraphEdge(
                            id=f"road:{mode.value}:origin->{node.id}",
                            from_node=ORIGIN_ID,
                            to_node=node.id,
                            kind=EdgeKind.ROAD_ACCESS,
                            mode=mode,
                            distance_meters=d_access,
                            needs_enrichment=True,
                            provenance=_access_prov(
                                "Road access placeholder; geometry/time via enrichment",
                                access_at,
                            ),
                            metadata={"enrichment": "road_geometry_time"},
                        )
                    )
                    linked = True
            if linked:
                origin_access_ids.append(node.id)

        for d_egress, node in egress_candidates:
            linked = False
            if (
                constraints.mode_allowed(MobilityMode.WALK)
                and d_egress <= limits.max_walking_egress_meters
            ):
                g.add_edge(
                    GraphEdge(
                        id=f"walk:{node.id}->destination",
                        from_node=node.id,
                        to_node=DEST_ID,
                        kind=EdgeKind.WALK,
                        mode=MobilityMode.WALK,
                        distance_meters=d_egress,
                        provenance=_access_prov("Walking egress", access_at),
                    )
                )
                linked = True
            if limits.allow_road_access and d_egress <= limits.max_road_access_meters:
                for mode_token in limits.road_access_modes:
                    if not constraints.mode_allowed(mode_token):
                        continue
                    mode = _mode_from_token(mode_token)
                    g.add_edge(
                        GraphEdge(
                            id=f"road:{mode.value}:{node.id}->destination",
                            from_node=node.id,
                            to_node=DEST_ID,
                            kind=EdgeKind.ROAD_ACCESS,
                            mode=mode,
                            distance_meters=d_egress,
                            needs_enrichment=True,
                            provenance=_access_prov(
                                "Road egress placeholder; geometry/time via enrichment",
                                access_at,
                            ),
                            metadata={"enrichment": "road_geometry_time"},
                        )
                    )
                    linked = True
            if linked:
                dest_access_ids.append(node.id)

        # Stash for search metadata (not part of MobilityNetworkGraph contract).
        g.provenance_notes = list(g.provenance_notes)  # ensure mutable copy
        self._last_access_meta = {
            "origin_access_nodes": origin_access_ids,
            "destination_access_nodes": dest_access_ids,
            "origin_access_count": len(origin_access_ids),
            "destination_access_count": len(dest_access_ids),
        }
        return g

    def _edge_allowed(
        self, edge: GraphEdge, constraints: JourneyConstraints
    ) -> bool:
        return constraints.mode_allowed(edge.mode)

    def _transfer_delta(
        self, state: _Partial, edge_or_route_id: Optional[str], *, interchange: bool
    ) -> Tuple[int, Optional[str]]:
        new_transfers = state.transfers
        new_last = state.last_transit_route
        if interchange:
            return new_transfers + 1, new_last
        if edge_or_route_id is None:
            return new_transfers, new_last
        if (
            state.last_transit_route is not None
            and edge_or_route_id != state.last_transit_route
        ):
            new_transfers += 1
        new_last = edge_or_route_id
        return new_transfers, new_last

    def _enqueue_route_boardings(
        self,
        *,
        state: _Partial,
        graph: MobilityNetworkGraph,
        transit_routes: Set[str],
        limits: SearchLimits,
        dest_lat: float,
        dest_lon: float,
        best: Dict[Tuple[Any, ...], Tuple[int, int, float]],
        heap: List[Tuple[float, int, float, int, int, _Partial]],
        alight_cache: Dict[Tuple[str, str], List[Tuple[str, Tuple[str, ...], float]]],
        tie: int,
        edges_considered: int,
        candidates_pruned: int,
    ) -> Tuple[int, int, int]:
        """Expand transit as route-continuation rides (one logical leg each)."""
        for route_id in sorted(transit_routes):
            cache_key = (state.node_id, route_id)
            if cache_key not in alight_cache:
                raw = _alightings_along_route(graph, state.node_id, route_id)
                alight_cache[cache_key] = _filter_alightings(
                    graph, state.node_id, raw, dest_lat, dest_lon
                )
            alightings = alight_cache[cache_key]
            if not alightings:
                continue

            new_transfers, new_last = self._transfer_delta(
                state, route_id, interchange=False
            )
            if new_transfers > limits.max_transfers:
                continue

            new_legs = state.legs + 1
            if new_legs > limits.max_legs:
                continue

            edges_considered += 1  # one logical boarding considered
            sample_eids = alightings[0][1]
            ride_mode = graph.edges[sample_eids[0]].mode.value
            for to_node, ride_eids, _ride_dist in alightings:
                nxt = _Partial(
                    node_id=to_node,
                    edge_ids=state.edge_ids + ride_eids,
                    transfers=new_transfers,
                    walking_m=state.walking_m,
                    last_transit_route=new_last,
                    legs=new_legs,
                    modes=state.modes + (ride_mode,),
                )
                if self._try_enqueue(
                    nxt, best, heap, graph, dest_lat, dest_lon, tie
                ):
                    tie += 1
                else:
                    candidates_pruned += 1
        return tie, edges_considered, candidates_pruned

    def _search(
        self,
        graph: MobilityNetworkGraph,
        request: JourneyBuildRequest,
        limits: SearchLimits,
        constraints: JourneyConstraints,
        warnings: List[str],
    ) -> Tuple[List[Journey], Dict[str, Any]]:
        dest_lat, dest_lon = request.destination
        start = _Partial(
            node_id=ORIGIN_ID,
            edge_ids=(),
            transfers=0,
            walking_m=0.0,
            last_transit_route=None,
            legs=0,
            modes=(),
        )
        # Heap entries: (f, transfers, walking, legs, tie, state)
        tie = 0
        h0 = _heuristic_m(graph, start.node_id, dest_lat, dest_lon)
        heap: List[Tuple[float, int, float, int, int, _Partial]] = []
        heapq.heappush(
            heap,
            (_g_cost(start) + h0, 0, 0.0, 0, tie, start),
        )
        best: Dict[Tuple[Any, ...], Tuple[int, int, float]] = {
            start.dominance_key: (0, 0, 0.0)
        }

        found: List[_Partial] = []
        sig_counts: Dict[Tuple[str, ...], int] = {}
        nodes_explored = 0
        edges_considered = 0
        candidates_generated = 0
        dominance_pruned = 0
        constraint_pruned = 0
        leg_limit_pruned = 0
        duplicate_signature_skipped = 0
        dest_reaches = 0
        max_depth = 0
        termination = "exhausted"
        soft_cap = limits.max_candidates * _COLLECTION_SOFT_MULT
        hard_cap = limits.max_candidates * _COLLECTION_HARD_MULT

        # Cache filtered route alightings from (node, route).
        alight_cache: Dict[Tuple[str, str], List[Tuple[str, Tuple[str, ...], float]]] = {}

        while heap:
            _f_score, _, _, _, _, state = heapq.heappop(heap)
            nodes_explored += 1
            max_depth = max(max_depth, state.legs)

            if nodes_explored > limits.max_nodes_explored:
                warnings.append("MAX_NODES_EXPLORED")
                termination = "max_nodes_explored"
                break

            if state.node_id == DEST_ID and state.edge_ids:
                dest_reaches += 1
                sig = collapse_mode_tokens(state.modes)
                if sig_counts.get(sig, 0) >= _PER_SIGNATURE_CAP:
                    duplicate_signature_skipped += 1
                else:
                    sig_counts[sig] = sig_counts.get(sig, 0) + 1
                    found.append(state)
                    candidates_generated += 1

                patterns = {transit_pattern(s) for s in sig_counts}
                patterns.discard(())  # ignore pure road / walk-only
                if dest_reaches >= hard_cap:
                    termination = "candidate_cap"
                    break
                if dest_reaches >= soft_cap and len(patterns) >= 2:
                    # ≥2 distinct transit projections (e.g. bmtc vs bmtc+metro)
                    # after a soft collection window — not a mode quota.
                    termination = "candidate_cap"
                    break
                continue

            if state.legs >= limits.max_legs:
                leg_limit_pruned += 1
                continue

            outgoing = sorted(graph.outgoing(state.node_id), key=lambda e: e.id)

            # --- Non-transit single-hop expansions (walk / road / interchange) ---
            transit_routes: Set[str] = set()
            for edge in outgoing:
                edges_considered += 1
                if not self._edge_allowed(edge, constraints):
                    constraint_pruned += 1
                    continue

                if edge.kind in _TRANSIT_KINDS and edge.route_id:
                    transit_routes.add(edge.route_id)
                    continue  # handled via route continuation below

                if edge.kind in _TRANSIT_KINDS and not edge.route_id:
                    new_transfers, new_last = self._transfer_delta(
                        state, None, interchange=False
                    )
                    if state.last_transit_route is not None:
                        new_transfers = state.transfers + 1
                    if new_transfers > limits.max_transfers:
                        continue
                    walk_add = 0.0
                    if edge.mode == MobilityMode.WALK and edge.distance_meters:
                        walk_add = float(edge.distance_meters)
                    new_walk = state.walking_m + walk_add
                    if (
                        constraints.max_walking_meters is not None
                        and new_walk > constraints.max_walking_meters
                    ):
                        constraint_pruned += 1
                        continue
                    new_legs = state.legs + 1
                    if new_legs > limits.max_legs:
                        leg_limit_pruned += 1
                        continue
                    nxt = _Partial(
                        node_id=edge.to_node,
                        edge_ids=state.edge_ids + (edge.id,),
                        transfers=new_transfers,
                        walking_m=new_walk,
                        last_transit_route=new_last,
                        legs=new_legs,
                        modes=state.modes + (edge.mode.value,),
                    )
                    if self._try_enqueue(
                        nxt, best, heap, graph, dest_lat, dest_lon, tie
                    ):
                        tie += 1
                    else:
                        dominance_pruned += 1
                    continue

                # Walk / road / interchange / transfer_walk
                interchange = edge.kind == EdgeKind.INTERCHANGE
                new_transfers, new_last = self._transfer_delta(
                    state,
                    None,
                    interchange=interchange,
                )
                if new_transfers > limits.max_transfers:
                    continue

                walk_add = 0.0
                if edge.mode == MobilityMode.WALK and edge.distance_meters:
                    walk_add = float(edge.distance_meters)
                new_walk = state.walking_m + walk_add
                if (
                    constraints.max_walking_meters is not None
                    and new_walk > constraints.max_walking_meters
                ):
                    constraint_pruned += 1
                    continue

                new_legs = state.legs + 1
                if new_legs > limits.max_legs:
                    leg_limit_pruned += 1
                    continue

                nxt = _Partial(
                    node_id=edge.to_node,
                    edge_ids=state.edge_ids + (edge.id,),
                    transfers=new_transfers,
                    walking_m=new_walk,
                    last_transit_route=(
                        new_last if not interchange else state.last_transit_route
                    ),
                    legs=new_legs,
                    modes=state.modes + (edge.mode.value,),
                )
                if self._try_enqueue(nxt, best, heap, graph, dest_lat, dest_lon, tie):
                    tie += 1
                else:
                    dominance_pruned += 1

                # Access lookahead: when leaving the origin overlay, board
                # transit immediately from the access stop so direct rides from
                # every nearby stop enter the open set (not only the first stop
                # A* happens to expand).
                if state.node_id == ORIGIN_ID and nxt.node_id != DEST_ID:
                    stop_routes = {
                        e.route_id
                        for e in graph.outgoing(nxt.node_id)
                        if e.kind in _TRANSIT_KINDS
                        and e.route_id
                        and self._edge_allowed(e, constraints)
                    }
                    tie, edges_considered, board_pruned = (
                        self._enqueue_route_boardings(
                            state=nxt,
                            graph=graph,
                            transit_routes=stop_routes,
                            limits=limits,
                            dest_lat=dest_lat,
                            dest_lon=dest_lon,
                            best=best,
                            heap=heap,
                            alight_cache=alight_cache,
                            tie=tie,
                            edges_considered=edges_considered,
                            candidates_pruned=0,
                        )
                    )
                    dominance_pruned += board_pruned

            # --- Route-continuation expansions (one logical transit leg) ---
            tie, edges_considered, board_pruned = self._enqueue_route_boardings(
                state=state,
                graph=graph,
                transit_routes=transit_routes,
                limits=limits,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                best=best,
                heap=heap,
                alight_cache=alight_cache,
                tie=tie,
                edges_considered=edges_considered,
                candidates_pruned=0,
            )
            dominance_pruned += board_pruned

        else:
            termination = "exhausted"

        # Pre-materialize diversity filter (arrival order already signature-capped).
        keep_n = max(limits.max_candidates * _COLLECTION_SOFT_MULT, limits.max_candidates)
        partials, part_meta = select_diverse_partials(
            found, max_keep=keep_n, per_signature=_PER_SIGNATURE_CAP
        )

        journeys = [
            self._materialize(graph, request, p, warnings) for p in partials
        ]
        journeys = [j for j in journeys if j.temporal_feasibility != "infeasible"]

        access_meta = getattr(self, "_last_access_meta", {})
        generated_sigs = [
            " → ".join(collapse_mode_tokens(p.modes)) for p in found
        ]
        metro_generated = sum(
            1 for p in found if "metro" in collapse_mode_tokens(p.modes)
        )
        meta = {
            "nodes_explored": nodes_explored,
            "edges_considered": edges_considered,
            "candidates_generated": candidates_generated,
            "candidates_pruned": dominance_pruned,  # backward-compatible alias
            "dominance_pruned": dominance_pruned,
            "constraint_pruned": constraint_pruned,
            "leg_limit_pruned": leg_limit_pruned,
            "node_limit_pruned": 1 if termination == "max_nodes_explored" else 0,
            "duplicate_signature_skipped": duplicate_signature_skipped,
            "dest_reaches": dest_reaches,
            "partials_reached_destination": dest_reaches,
            "partials_kept_for_materialize": len(partials),
            "max_depth_reached": max_depth,
            "search_termination_reason": termination,
            "origin_access_nodes": access_meta.get("origin_access_nodes", []),
            "destination_access_nodes": access_meta.get("destination_access_nodes", []),
            "origin_access_count": access_meta.get("origin_access_count", 0),
            "destination_access_count": access_meta.get("destination_access_count", 0),
            "heuristic": "haversine_to_destination",
            "route_continuation": True,
            "access_boarding_lookahead": True,
            "collection_soft_mult": _COLLECTION_SOFT_MULT,
            "collection_hard_mult": _COLLECTION_HARD_MULT,
            "collection_soft_cap": soft_cap,
            "collection_hard_cap": hard_cap,
            "per_signature_cap": _PER_SIGNATURE_CAP,
            "generated_mode_signatures": sorted(set(generated_sigs)),
            "generated_signature_counts": {
                s: generated_sigs.count(s) for s in sorted(set(generated_sigs))
            },
            "metro_containing_generated": metro_generated,
            "transit_patterns_generated": [
                " → ".join(p) if p else "(none)"
                for p in sorted({transit_pattern(s) for s in sig_counts})
            ],
            **part_meta,
        }
        if not journeys:
            warnings.append("NO_PATH_FOUND")
        return journeys, meta

    def _try_enqueue(
        self,
        nxt: _Partial,
        best: Dict[Tuple[Any, ...], Tuple[int, int, float]],
        heap: List[Tuple[float, int, float, int, int, _Partial]],
        graph: MobilityNetworkGraph,
        dest_lat: float,
        dest_lon: float,
        tie: int,
    ) -> bool:
        metrics = (nxt.transfers, nxt.legs, nxt.walking_m)
        prev = best.get(nxt.dominance_key)
        if prev is not None and metrics >= prev:
            return False
        best[nxt.dominance_key] = metrics
        h = _heuristic_m(graph, nxt.node_id, dest_lat, dest_lon)
        f = _g_cost(nxt) + h
        heapq.heappush(
            heap,
            (f, nxt.transfers, nxt.walking_m, nxt.legs, tie, nxt),
        )
        return True

    def _materialize(
        self,
        graph: MobilityNetworkGraph,
        request: JourneyBuildRequest,
        partial: _Partial,
        warnings: List[str],
    ) -> Journey:
        raw_edges = [graph.edges[eid] for eid in partial.edge_ids]
        compressed = _compress_edges(raw_edges)
        legs: List[JourneyLeg] = []
        enrichments: List[EnrichmentRequirement] = []
        modes: List[str] = []
        prov_sources: List[str] = []
        transit_legs = 0
        road_legs = 0
        transfers = 0
        last_transit_route: Optional[str] = None
        schedule_known_any = False
        schedule_missing = False
        n = len(compressed)

        for idx, edge in enumerate(compressed):
            from_node = graph.nodes[edge.from_node]
            to_node = graph.nodes[edge.to_node]
            is_transfer = False
            if edge.kind in {EdgeKind.BUS, EdgeKind.METRO}:
                transit_legs += 1
                if (
                    last_transit_route is not None
                    and edge.route_id
                    and edge.route_id != last_transit_route
                ):
                    is_transfer = True
                    transfers += 1
                if edge.route_id:
                    last_transit_route = edge.route_id
                if edge.schedule_meta.get("schedule_available"):
                    schedule_known_any = True
                else:
                    schedule_missing = True
            if edge.kind == EdgeKind.INTERCHANGE:
                is_transfer = True
                transfers += 1
            if edge.kind in {EdgeKind.ROAD_ACCESS, EdgeKind.ROAD_DIRECT}:
                road_legs += 1

            modes.append(edge.mode.value)
            if edge.provenance and edge.provenance.source:
                prov_sources.append(edge.provenance.source)

            role = infer_segment_role(
                edge.kind,
                from_node_id=edge.from_node,
                to_node_id=edge.to_node,
                is_first=(idx == 0),
                is_last=(idx == n - 1),
                is_only=(n == 1),
            )

            leg = JourneyLeg(
                index=idx,
                mode=edge.mode,
                from_node_id=edge.from_node,
                to_node_id=edge.to_node,
                edge_id=edge.id,
                edge_kind=edge.kind,
                from_ref=from_node.source_ref,
                to_ref=to_node.source_ref,
                from_name=from_node.name or None,
                to_name=to_node.name or None,
                route_id=edge.route_id,
                provider=edge.provider,
                distance_meters=edge.distance_meters,
                is_transfer=is_transfer or edge.is_transfer,
                needs_enrichment=edge.needs_enrichment,
                segment_role=role,
                provenance=edge.provenance,
                metadata=dict(edge.metadata),
            )
            leg = annotate_leg_economics(leg)
            legs.append(leg)
            if edge.needs_enrichment:
                enrichments.append(
                    EnrichmentRequirement(
                        requirement_type="road_geometry_time",
                        leg_index=idx,
                        mode=edge.mode.value,
                        from_lat=from_node.latitude,
                        from_lon=from_node.longitude,
                        to_lat=to_node.latitude,
                        to_lon=to_node.longitude,
                        notes="Resolve via live routing layer; not fabricated here.",
                    )
                )

        econ = aggregate_journey_economics(legs)

        if schedule_known_any and not schedule_missing:
            temporal = "known"
        elif any(e.kind in {EdgeKind.BUS, EdgeKind.METRO} for e in compressed):
            temporal = "unknown"
        elif any(leg.needs_enrichment for leg in legs):
            temporal = "unknown"
        elif all(leg.duration_status == "known" for leg in legs):
            temporal = "known"
        else:
            temporal = "unknown"

        cid = _candidate_id(partial.edge_ids)
        j_warnings: List[str] = []
        if temporal == "unknown":
            j_warnings.append(
                "TEMPORAL_FEASIBILITY_UNKNOWN (no fabricated schedules)"
            )
        if econ["cost_status"] == "unknown":
            j_warnings.append("JOURNEY_COST_UNKNOWN (partial or missing fares)")

        return Journey(
            candidate_id=cid,
            origin=request.origin,
            destination=request.destination,
            legs=legs,
            transfer_count=transfers,
            walking_distance_meters=econ["walking_distance_meters"],
            transit_leg_count=transit_legs,
            road_leg_count=road_legs,
            modes=modes,
            snapshot_versions=dict(graph.snapshot_versions),
            provenance_sources=sorted(set(prov_sources)),
            enrichment_requirements=enrichments,
            temporal_feasibility=temporal,
            warnings=j_warnings,
            total_cost_inr=econ["total_cost_inr"],
            cost_status=econ["cost_status"],
            total_duration_seconds=econ["total_duration_seconds"],
            duration_status=econ["duration_status"],
            access_walking_meters=econ["access_walking_meters"],
            transfer_walking_meters=econ["transfer_walking_meters"],
            egress_walking_meters=econ["egress_walking_meters"],
            mode_signature=mode_signature(legs),
        )


def _compress_edges(edges: List[GraphEdge]) -> List[GraphEdge]:
    """Merge consecutive same-route transit hops into one logical leg edge."""
    if not edges:
        return []
    out: List[GraphEdge] = []
    current = edges[0]
    for nxt in edges[1:]:
        same_transit = (
            current.kind == nxt.kind
            and current.kind in {EdgeKind.BUS, EdgeKind.METRO}
            and current.route_id
            and current.route_id == nxt.route_id
            and current.to_node == nxt.from_node
        )
        if same_transit:
            dist = None
            if current.distance_meters is not None and nxt.distance_meters is not None:
                dist = current.distance_meters + nxt.distance_meters
            current = GraphEdge(
                id=f"{current.id}+{nxt.to_node}",
                from_node=current.from_node,
                to_node=nxt.to_node,
                kind=current.kind,
                mode=current.mode,
                provider=current.provider,
                route_id=current.route_id,
                distance_meters=dist,
                is_transfer=current.is_transfer,
                needs_enrichment=current.needs_enrichment,
                confidence=current.confidence,
                provenance=current.provenance,
                schedule_meta=dict(current.schedule_meta),
                metadata=dict(current.metadata),
            )
        else:
            out.append(current)
            current = nxt
    out.append(current)
    return out


def _candidate_id(edge_ids: Tuple[str, ...]) -> str:
    blob = "|".join(edge_ids).encode("utf-8")
    return "j_" + hashlib.sha256(blob).hexdigest()[:12]
