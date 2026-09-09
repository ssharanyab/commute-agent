"""
Deterministic place → published mobility-node matching (Phase 7K-4).

Conservative: only snap when proximity is tight. Does not snap area labels
by name. Unknown / uncertain → place (not a random nearby node).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.journey_builder.endpoints import (
    EndpointKind,
    JourneyEndpoint,
    network_for_node_id,
)
from src.journey_builder.graph import (
    MobilityNetworkGraph,
    NodeKind,
    haversine_m,
    station_node_id,
    stop_node_id,
)
from src.network.repository import StaticMobilityDataRepository

# Conservative: only treat as "already at node" inside this radius.
DEFAULT_ANCHOR_RADIUS_M = 25.0

# Places (New) / Geocoding type tokens that justify transit-node snap.
_TRANSIT_TYPE_HINTS = frozenset(
    {
        "subway_station",
        "train_station",
        "transit_station",
        "light_rail_station",
        "bus_station",
        "bus_stop",
    }
)


@dataclass(frozen=True)
class NodeMatch:
    node_id: str
    network: str
    distance_meters: float
    kind: str
    name: Optional[str] = None

    def to_endpoint(
        self,
        *,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        place_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> JourneyEndpoint:
        return JourneyEndpoint.network_node(
            network=self.network,
            node_id=self.node_id,
            lat=lat,
            lon=lon,
            place_id=place_id,
            display_name=display_name or self.name,
        )


def _iter_published_nodes(
    repository: StaticMobilityDataRepository,
) -> List[Tuple[str, str, float, float, str, Optional[str]]]:
    """Return (node_id, network, lat, lon, kind, name)."""
    out: List[Tuple[str, str, float, float, str, Optional[str]]] = []
    payloads_fn = getattr(repository, "_all_active_payloads", None)
    payloads: Sequence[Dict[str, Any]] = []
    if callable(payloads_fn):
        payloads = list(payloads_fn() or [])
    else:
        for name in ("bmrcl", "bmtc"):
            snap = repository.get_active_snapshot(name)
            if snap is not None:
                payloads.append(dict(snap.payload or {}))

    for payload in payloads:
        for raw in payload.get("stations") or []:
            lat, lon = raw.get("latitude"), raw.get("longitude")
            if lat is None or lon is None:
                continue
            sid = str(raw.get("id") or "")
            if not sid:
                continue
            out.append(
                (
                    station_node_id(sid),
                    "bmrcl",
                    float(lat),
                    float(lon),
                    "metro_station",
                    str(raw.get("name") or "") or None,
                )
            )
        for raw in payload.get("stops") or []:
            lat, lon = raw.get("latitude"), raw.get("longitude")
            if lat is None or lon is None:
                continue
            sid = str(raw.get("id") or "")
            if not sid:
                continue
            out.append(
                (
                    stop_node_id(sid),
                    "bmtc",
                    float(lat),
                    float(lon),
                    "bus_stop",
                    str(raw.get("name") or "") or None,
                )
            )
    return out


def nearest_published_nodes(
    repository: StaticMobilityDataRepository,
    *,
    lat: float,
    lon: float,
    limit: int = 5,
) -> List[NodeMatch]:
    scored: List[NodeMatch] = []
    for node_id, network, nlat, nlon, kind, name in _iter_published_nodes(repository):
        d = haversine_m(lat, lon, nlat, nlon)
        scored.append(
            NodeMatch(
                node_id=node_id,
                network=network,
                distance_meters=d,
                kind=kind,
                name=name,
            )
        )
    scored.sort(key=lambda m: (m.distance_meters, m.node_id))
    return scored[:limit]


def places_types_indicate_transit(types: Optional[Sequence[str]]) -> bool:
    if not types:
        return False
    normalized = {str(t).strip().lower() for t in types if t}
    return bool(normalized & _TRANSIT_TYPE_HINTS)


def match_place_to_network_node(
    repository: StaticMobilityDataRepository,
    *,
    lat: float,
    lon: float,
    place_types: Optional[Sequence[str]] = None,
    display_name: Optional[str] = None,
    place_id: Optional[str] = None,
    max_distance_m: float = DEFAULT_ANCHOR_RADIUS_M,
    require_transit_type_hint: bool = False,
) -> Optional[NodeMatch]:
    """
    Conservative snap to a published node.

    If ``require_transit_type_hint`` is True, Places types must indicate
    transit. When types are unavailable, proximity alone within
    ``max_distance_m`` is accepted only when the caller opts in by setting
    require_transit_type_hint=False (used when client already asserts a
    station selection via explicit network_node, not for bare geocodes).
    """
    nearest = nearest_published_nodes(repository, lat=lat, lon=lon, limit=1)
    if not nearest:
        return None
    best = nearest[0]
    if best.distance_meters > max_distance_m:
        return None
    if require_transit_type_hint and not places_types_indicate_transit(place_types):
        return None
    return best


def resolve_endpoint_for_plan(
    repository: Optional[StaticMobilityDataRepository],
    *,
    explicit: Optional[JourneyEndpoint],
    label: str,
    lat: Optional[float],
    lon: Optional[float],
    place_id: Optional[str] = None,
    place_types: Optional[Sequence[str]] = None,
    graph: Optional[MobilityNetworkGraph] = None,
) -> JourneyEndpoint:
    """
    Produce a JourneyEndpoint for plan/orchestration.

    Precedence:
      1. Explicit network_node (validated against graph/repo)
      2. Explicit place
      3. Legacy lat/lon → place (optional conservative snap when types say transit)
    """
    from src.journey_builder.endpoints import EndpointResolutionError

    if explicit is not None and explicit.is_network_node:
        node_id = explicit.node_id or ""
        if graph is not None and node_id not in graph.nodes:
            raise EndpointResolutionError(
                f"Unknown network node {node_id!r}",
                code="UNKNOWN_NETWORK_NODE",
            )
        published = (
            {n[0]: n for n in _iter_published_nodes(repository)}
            if repository is not None
            else {}
        )
        if graph is None and repository is not None and node_id not in published:
            raise EndpointResolutionError(
                f"Unknown network node {node_id!r}",
                code="UNKNOWN_NETWORK_NODE",
            )
        lat, lon = explicit.lat, explicit.lon
        name = explicit.display_name
        if (lat is None or lon is None) and graph is not None:
            node = graph.nodes.get(node_id)
            if node is not None and node.latitude is not None:
                lat, lon = node.latitude, node.longitude
                name = name or node.name
        if (lat is None or lon is None) and node_id in published:
            _nid, _net, plat, plon, _kind, pname = published[node_id]
            lat, lon = plat, plon
            name = name or pname
        return JourneyEndpoint.network_node(
            network=explicit.network or network_for_node_id(node_id) or "",
            node_id=node_id,
            lat=lat,
            lon=lon,
            place_id=explicit.place_id,
            display_name=name,
        )

    if explicit is not None and explicit.is_place:
        if explicit.lat is None or explicit.lon is None:
            raise EndpointResolutionError(
                "place endpoint missing coordinates",
                code="INVALID_PLACE_ENDPOINT",
            )
        return explicit

    if lat is None or lon is None:
        raise EndpointResolutionError(
            f"Unresolved coordinates for {label!r}",
            code="COORDINATES_UNRESOLVED",
        )

    # Optional snap only with transit type hints (never bare area labels).
    if repository is not None and places_types_indicate_transit(place_types):
        match = match_place_to_network_node(
            repository,
            lat=float(lat),
            lon=float(lon),
            place_types=place_types,
            display_name=label,
            place_id=place_id,
            require_transit_type_hint=True,
        )
        if match is not None:
            return match.to_endpoint(
                lat=float(lat),
                lon=float(lon),
                place_id=place_id,
                display_name=label,
            )

    return JourneyEndpoint.place(
        lat=float(lat),
        lon=float(lon),
        place_id=place_id,
        display_name=label or None,
    )


def validate_node_in_graph(graph: MobilityNetworkGraph, node_id: str) -> None:
    from src.journey_builder.endpoints import EndpointResolutionError

    if node_id not in graph.nodes:
        raise EndpointResolutionError(
            f"Unknown network node {node_id!r}",
            code="UNKNOWN_NETWORK_NODE",
        )
    kind = graph.nodes[node_id].kind
    if kind not in {
        NodeKind.BUS_STOP,
        NodeKind.METRO_STATION,
        NodeKind.INTERCHANGE,
    }:
        raise EndpointResolutionError(
            f"Node {node_id!r} is not a mobility stop/station",
            code="INVALID_NETWORK_NODE",
        )
