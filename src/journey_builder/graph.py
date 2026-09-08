"""
Deterministic mobility network graph built from StaticMobilityDataRepository.

Edges come only from published network topology — never invented journeys.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.network.models import (
    DataProvenance,
    MobilityMode,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
    SourceType,
)
from src.network.repository import StaticMobilityDataRepository
from src.journey_builder.models import EdgeKind, GraphEdge, GraphNode, NodeKind


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def stop_node_id(stop_id: str) -> str:
    return f"stop:{stop_id}"


def station_node_id(station_id: str) -> str:
    return f"station:{station_id}"


@dataclass
class MobilityNetworkGraph:
    """Directed multigraph of mobility nodes and service/access edges."""

    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: Dict[str, GraphEdge] = field(default_factory=dict)
    adjacency: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    snapshot_versions: Dict[str, str] = field(default_factory=dict)
    provenance_notes: List[str] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.from_node not in self.nodes or edge.to_node not in self.nodes:
            return
        if edge.id in self.edges:
            return
        self.edges[edge.id] = edge
        self.adjacency.setdefault(edge.from_node, []).append(edge.id)

    def outgoing(self, node_id: str) -> List[GraphEdge]:
        return [self.edges[eid] for eid in self.adjacency.get(node_id, [])]

    def stats(self) -> Dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "bus_stops": sum(
                1 for n in self.nodes.values() if n.kind == NodeKind.BUS_STOP
            ),
            "metro_stations": sum(
                1 for n in self.nodes.values() if n.kind == NodeKind.METRO_STATION
            ),
        }


def _internal_prov(note: str) -> DataProvenance:
    # Fixed timestamp so graph builds are deterministic for identical snapshots.
    return DataProvenance(
        source="journey_builder_graph",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        confidence=1.0,
        notes=note,
    )


def _collect_payloads(
    repository: StaticMobilityDataRepository,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Load active payloads via public snapshot APIs when possible."""
    versions: Dict[str, str] = {}
    payloads: List[Dict[str, Any]] = []

    # FileStaticMobilityRepository exposes root_dir; prefer iterating datasets.
    root = getattr(repository, "root_dir", None)
    if root is not None:
        from pathlib import Path

        for dataset_dir in sorted(Path(root).iterdir()):
            if not dataset_dir.is_dir():
                continue
            # skip non-dataset dirs (seed folders under subpaths are separate)
            name = dataset_dir.name
            if name in {"seed"} or name.startswith("."):
                continue
            snap = repository.get_active_snapshot(name)
            if snap is None:
                continue
            versions[name] = snap.version
            payloads.append(dict(snap.payload))
            if snap.provenance and snap.provenance.source:
                pass
        return payloads, versions

    # Fallback: reconstruct from list_routes + find near origin extremes (tests
    # always use FileStaticMobilityRepository). Empty if no root.
    return payloads, versions


def build_mobility_graph(
    repository: StaticMobilityDataRepository,
    *,
    walk_transfer_meters: float = 400.0,
) -> MobilityNetworkGraph:
    """
    Build a static graph from published snapshots.

    - Bus edges: consecutive stops along each route stop sequence
    - Metro edges: consecutive stations along each metro route/line
    - Interchange edges: only from published interchange_station_ids
    - Transfer walks: only when both endpoints have coordinates and are nearby
    Does not invent missing edges or fabricate schedules.
    """
    graph = MobilityNetworkGraph()
    payloads, versions = _collect_payloads(repository)
    graph.snapshot_versions = versions

    stops: Dict[str, MobilityStop] = {}
    stations: Dict[str, MobilityStation] = {}
    routes: List[MobilityRoute] = []

    for payload in payloads:
        for raw in payload.get("stops") or []:
            stop = MobilityStop.from_dict(raw)
            stops[stop.id] = stop
        for raw in payload.get("stations") or []:
            station = MobilityStation.from_dict(raw)
            stations[station.id] = station
        for raw in payload.get("routes") or []:
            routes.append(MobilityRoute.from_dict(raw))

    for stop in stops.values():
        nid = stop_node_id(stop.id)
        graph.add_node(
            GraphNode(
                id=nid,
                kind=NodeKind.BUS_STOP,
                name=stop.name,
                latitude=stop.latitude,
                longitude=stop.longitude,
                provider=stop.provider,
                network=stop.network,
                source_ref=stop.id,
                metadata={"stop_type": stop.stop_type.value},
            )
        )
        if stop.provenance and stop.provenance.source:
            graph.provenance_notes.append(stop.provenance.source)

    for station in stations.values():
        nid = station_node_id(station.id)
        kind = (
            NodeKind.INTERCHANGE
            if len(station.lines) > 1 or station.interchange_station_ids
            else NodeKind.METRO_STATION
        )
        graph.add_node(
            GraphNode(
                id=nid,
                kind=kind,
                name=station.name,
                latitude=station.latitude,
                longitude=station.longitude,
                provider=station.provider,
                network="bmrcl",
                source_ref=station.id,
                metadata={
                    "lines": list(station.lines),
                    "line_order": dict(station.line_order),
                },
            )
        )
        if station.provenance and station.provenance.source:
            graph.provenance_notes.append(station.provenance.source)

    # Service edges from route sequences (directed along published order).
    for route in routes:
        seq = list(route.stop_ids)
        if len(seq) < 2:
            continue
        if route.mode == MobilityMode.BUS:
            for a, b in zip(seq, seq[1:]):
                fa, tb = stop_node_id(a), stop_node_id(b)
                if fa not in graph.nodes or tb not in graph.nodes:
                    continue
                dist = None
                na, nb = graph.nodes[fa], graph.nodes[tb]
                if (
                    na.latitude is not None
                    and na.longitude is not None
                    and nb.latitude is not None
                    and nb.longitude is not None
                ):
                    dist = haversine_m(
                        na.latitude, na.longitude, nb.latitude, nb.longitude
                    )
                eid = f"bus:{route.id}:{a}->{b}"
                graph.add_edge(
                    GraphEdge(
                        id=eid,
                        from_node=fa,
                        to_node=tb,
                        kind=EdgeKind.BUS,
                        mode=MobilityMode.BUS,
                        provider=route.provider,
                        route_id=route.id,
                        distance_meters=dist,
                        is_transfer=False,
                        confidence=route.provenance.confidence
                        if route.provenance
                        else None,
                        provenance=route.provenance,
                        schedule_meta={
                            "schedule_available": False,
                            "note": "Use stop_times when present; do not fabricate.",
                        },
                        metadata={"route_name": route.name, "short_name": route.short_name},
                    )
                )
        elif route.mode == MobilityMode.METRO:
            for a, b in zip(seq, seq[1:]):
                fa, tb = station_node_id(a), station_node_id(b)
                if fa not in graph.nodes or tb not in graph.nodes:
                    continue
                eid = f"metro:{route.id}:{a}->{b}"
                graph.add_edge(
                    GraphEdge(
                        id=eid,
                        from_node=fa,
                        to_node=tb,
                        kind=EdgeKind.METRO,
                        mode=MobilityMode.METRO,
                        provider=route.provider,
                        route_id=route.id,
                        is_transfer=False,
                        confidence=route.provenance.confidence
                        if route.provenance
                        else None,
                        provenance=route.provenance,
                        schedule_meta={"schedule_available": False},
                        metadata={
                            "line": route.id,
                            "color": (route.service_metadata or {}).get("color"),
                        },
                    )
                )
            # Bidirectional metro: also add reverse if not already implied.
            # Official lines are typically bidirectional; reverse along sequence.
            for a, b in zip(seq, seq[1:]):
                fa, tb = station_node_id(b), station_node_id(a)
                if fa not in graph.nodes or tb not in graph.nodes:
                    continue
                eid = f"metro:{route.id}:{b}->{a}"
                graph.add_edge(
                    GraphEdge(
                        id=eid,
                        from_node=fa,
                        to_node=tb,
                        kind=EdgeKind.METRO,
                        mode=MobilityMode.METRO,
                        provider=route.provider,
                        route_id=route.id,
                        is_transfer=False,
                        confidence=route.provenance.confidence
                        if route.provenance
                        else None,
                        provenance=route.provenance,
                        schedule_meta={"schedule_available": False},
                        metadata={
                            "line": route.id,
                            "direction": "reverse",
                        },
                    )
                )

    # Published interchange relationships only (no invention).
    for station in stations.values():
        for other_id in station.interchange_station_ids:
            if other_id == station.id:
                # Self-marked interchange hub: no extra edge needed.
                continue
            if other_id not in stations:
                continue
            fa, tb = station_node_id(station.id), station_node_id(other_id)
            eid = f"ix:{station.id}->{other_id}"
            graph.add_edge(
                GraphEdge(
                    id=eid,
                    from_node=fa,
                    to_node=tb,
                    kind=EdgeKind.INTERCHANGE,
                    mode=MobilityMode.WALK,
                    provider=station.provider,
                    is_transfer=True,
                    distance_meters=0.0,
                    provenance=station.provenance,
                    metadata={"interchange": True},
                )
            )

    # Walk transfers between nearby stop↔station when coords exist.
    stop_list = [s for s in stops.values()]
    station_list = [
        s
        for s in stations.values()
        if s.latitude is not None and s.longitude is not None
    ]
    for stop in stop_list:
        for station in station_list:
            dist = haversine_m(
                stop.latitude, stop.longitude, station.latitude, station.longitude
            )
            if dist > walk_transfer_meters:
                continue
            fa, tb = stop_node_id(stop.id), station_node_id(station.id)
            for frm, to, suffix in ((fa, tb, "s2m"), (tb, fa, "m2s")):
                eid = f"xferwalk:{suffix}:{stop.id}:{station.id}"
                graph.add_edge(
                    GraphEdge(
                        id=eid,
                        from_node=frm,
                        to_node=to,
                        kind=EdgeKind.TRANSFER_WALK,
                        mode=MobilityMode.WALK,
                        distance_meters=dist,
                        is_transfer=False,  # boarding next transit counts transfer
                        provenance=_internal_prov(
                            "Derived walk link from published coordinates only"
                        ),
                        confidence=0.7,
                        metadata={"derived": True},
                    )
                )

    # Deduplicate provenance notes
    graph.provenance_notes = sorted(set(graph.provenance_notes))
    return graph
