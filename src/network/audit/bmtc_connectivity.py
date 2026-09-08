"""
Phase 6A — BMTC connectivity / data-quality audit (read-only analysis).

Uses published FileStaticMobilityRepository snapshots only.
Does not invent stops, routes, BMRCL coordinates, or journey templates.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.agent.demo_od import (
    CANONICAL_DEMO_DEPARTURE,
    ELECTRONIC_CITY,
    MAJESTIC,
    DemoPlace,
)
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest, SearchLimits
from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import MobilityRoute, MobilityStop


DEFAULT_AUDIT_RADIUS_M = 800.0  # matches SearchLimits.max_walking_access_meters


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


@dataclass
class NearbyStop:
    stop_id: str
    name: str
    latitude: float
    longitude: float
    distance_meters: float
    route_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_bmtc_payload(
    repository: FileStaticMobilityRepository,
) -> Tuple[Dict[str, Any], Optional[Any]]:
    snap = repository.get_active_snapshot("bmtc")
    if snap is None:
        return {}, None
    return dict(snap.payload), snap


def _stops_and_routes(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, MobilityStop], List[MobilityRoute]]:
    stops = {
        s["id"]: MobilityStop.from_dict(s) for s in (payload.get("stops") or [])
    }
    routes = [MobilityRoute.from_dict(r) for r in (payload.get("routes") or [])]
    return stops, routes


def routes_serving_stop(
    routes: Sequence[MobilityRoute], stop_id: str
) -> List[str]:
    return [r.id for r in routes if stop_id in r.stop_ids]


def find_nearby_stops(
    stops: Dict[str, MobilityStop],
    routes: Sequence[MobilityRoute],
    anchor: DemoPlace,
    *,
    radius_m: float = DEFAULT_AUDIT_RADIUS_M,
) -> List[NearbyStop]:
    nearby: List[NearbyStop] = []
    for stop in stops.values():
        d = haversine_m(
            anchor.latitude, anchor.longitude, stop.latitude, stop.longitude
        )
        if d <= radius_m:
            nearby.append(
                NearbyStop(
                    stop_id=stop.id,
                    name=stop.name,
                    latitude=stop.latitude,
                    longitude=stop.longitude,
                    distance_meters=round(d, 1),
                    route_ids=routes_serving_stop(routes, stop.id),
                )
            )
    nearby.sort(key=lambda s: (s.distance_meters, s.stop_id))
    return nearby


def _stop_adjacency(routes: Sequence[MobilityRoute]) -> Dict[str, Set[str]]:
    """Directed edges from consecutive published route stop sequences."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    for route in routes:
        seq = list(route.stop_ids)
        for a, b in zip(seq, seq[1:]):
            if a != b:
                adj[a].add(b)
    return adj


def analyze_bmtc_connectivity(
    routes: Sequence[MobilityRoute],
    origin_stop_ids: Sequence[str],
    dest_stop_ids: Sequence[str],
) -> Dict[str, Any]:
    """
    Determine direct / transfer / none connectivity from published sequences.

    Direct: at least one route whose stop_ids include ≥1 origin and ≥1 dest stop
            with origin appearing before destination along the sequence.
    Transfer: no such direct route, but a directed path exists on the stop graph.
    """
    origin_set = set(origin_stop_ids)
    dest_set = set(dest_stop_ids)
    if not origin_set or not dest_set:
        return {
            "result": "none",
            "direct": False,
            "transfer": False,
            "reason": "missing_origin_or_destination_stops_within_radius",
            "direct_route_ids": [],
            "path_stop_count": None,
        }

    direct_routes: List[str] = []
    for route in routes:
        seq = list(route.stop_ids)
        if not seq:
            continue
        idx_o = [i for i, sid in enumerate(seq) if sid in origin_set]
        idx_d = [i for i, sid in enumerate(seq) if sid in dest_set]
        if idx_o and idx_d and min(idx_o) < max(idx_d):
            # Origin appears somewhere before a dest appearance (usable direction).
            if any(o < d for o in idx_o for d in idx_d):
                direct_routes.append(route.id)

    if direct_routes:
        return {
            "result": "direct",
            "direct": True,
            "transfer": False,
            "reason": "route_stop_sequence_covers_both_anchors",
            "direct_route_ids": sorted(direct_routes),
            "path_stop_count": None,
        }

    adj = _stop_adjacency(routes)
    # Multi-source BFS
    q: deque = deque()
    prev: Dict[str, Optional[str]] = {}
    for sid in origin_set:
        q.append(sid)
        prev[sid] = None
    found: Optional[str] = None
    while q:
        cur = q.popleft()
        if cur in dest_set:
            found = cur
            break
        for nxt in adj.get(cur, ()):
            if nxt not in prev:
                prev[nxt] = cur
                q.append(nxt)

    if found is None:
        return {
            "result": "none",
            "direct": False,
            "transfer": False,
            "reason": "no_path_in_published_stop_sequences",
            "direct_route_ids": [],
            "path_stop_count": None,
        }

    # Reconstruct path length
    path_len = 0
    cur: Optional[str] = found
    seen: Set[str] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        path_len += 1
        cur = prev[cur]

    return {
        "result": "transfer",
        "direct": False,
        "transfer": True,
        "reason": "path_exists_via_stop_sequence_graph",
        "direct_route_ids": [],
        "path_stop_count": path_len,
    }


def analyze_bmrcl_availability(
    repository: FileStaticMobilityRepository,
) -> Dict[str, Any]:
    snap = repository.get_active_snapshot("bmrcl")
    stations: List[dict] = []
    version = None
    source = "active_snapshot"
    if snap is not None:
        stations = list(snap.payload.get("stations") or [])
        version = snap.version
    else:
        seed = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "mobility_network"
            / "bmrcl"
            / "seed"
            / "bmrcl_network_seed.json"
        )
        if seed.exists():
            raw = json.loads(seed.read_text(encoding="utf-8"))
            stations = list(raw.get("stations") or [])
            version = raw.get("version")
            source = "seed_file"
        else:
            return {
                "bmrcl_snapshot_present": False,
                "stations_total": 0,
                "stations_with_coordinates": 0,
                "note": "No active bmrcl snapshot or seed file found.",
            }

    with_coords = 0
    for raw in stations:
        lat, lon = raw.get("latitude"), raw.get("longitude")
        if lat is not None and lon is not None:
            with_coords += 1
    return {
        "bmrcl_snapshot_present": snap is not None,
        "bmrcl_data_source": source,
        "version": version,
        "stations_total": len(stations),
        "stations_with_coordinates": with_coords,
        "note": (
            "Geographic BMTC↔BMRCL links require coordinates on both sides."
            if with_coords == 0
            else "Some BMRCL stations have coordinates."
        ),
    }


def analyze_bmtc_bmrcl_geographic(
    repository: FileStaticMobilityRepository,
    *,
    radius_m: float = DEFAULT_AUDIT_RADIUS_M,
) -> Dict[str, Any]:
    bmtc_payload, _ = _load_bmtc_payload(repository)
    bmtc_stops, _ = _stops_and_routes(bmtc_payload)
    bmrcl = analyze_bmrcl_availability(repository)
    if bmrcl["stations_with_coordinates"] == 0:
        return {
            "bmtc_to_bmrcl_possible": False,
            "reason": (
                "BMRCL stations lack published coordinates in the active/seed "
                "network data; geographic walk edges cannot be established "
                "without fabricating coordinates."
            ),
            "pairs_within_radius": 0,
            "audit_radius_meters": radius_m,
            "bmrcl": bmrcl,
        }

    snap = repository.get_active_snapshot("bmrcl")
    assert snap is not None
    pairs = 0
    for raw in snap.payload.get("stations") or []:
        lat, lon = raw.get("latitude"), raw.get("longitude")
        if lat is None or lon is None:
            continue
        for stop in bmtc_stops.values():
            if haversine_m(float(lat), float(lon), stop.latitude, stop.longitude) <= radius_m:
                pairs += 1
                break
    return {
        "bmtc_to_bmrcl_possible": pairs > 0,
        "reason": (
            "At least one BMTC stop lies within audit radius of a BMRCL station "
            "with coordinates."
            if pairs > 0
            else "No BMTC stop within audit radius of any coordinated BMRCL station."
        ),
        "pairs_within_radius": pairs,
        "audit_radius_meters": radius_m,
        "bmrcl": bmrcl,
    }


def journey_builder_smoke(
    repository: FileStaticMobilityRepository,
    *,
    departure_time: Optional[datetime] = None,
    radius_m: float = DEFAULT_AUDIT_RADIUS_M,
) -> Dict[str, Any]:
    """Run existing DynamicJourneyBuilder — no algorithm changes."""
    from src.journey_builder.graph import build_mobility_graph

    # Prefer a departure inside the feed calendar when meta is available.
    payload, snap = _load_bmtc_payload(repository)
    meta = payload.get("dataset_meta") or {}
    stats = meta.get("statistics") or {}
    earliest = stats.get("earliest_service_date") or meta.get("feed_start_date")
    dep = departure_time
    if dep is None and earliest and len(str(earliest)) == 8:
        # Use 08:00 UTC on earliest service date (deterministic).
        y, m, d = int(earliest[:4]), int(earliest[4:6]), int(earliest[6:8])
        dep = datetime(y, m, d, 8, 0, tzinfo=timezone.utc)
    if dep is None:
        dep = CANONICAL_DEMO_DEPARTURE

    limits = SearchLimits(
        max_walking_access_meters=radius_m,
        max_walking_egress_meters=radius_m,
    )
    graph = build_mobility_graph(
        repository, walk_transfer_meters=limits.max_walk_transfer_meters
    )
    builder = DynamicJourneyBuilder(repository, graph=graph, default_limits=limits)
    result = builder.build(
        JourneyBuildRequest(
            origin_lat=ELECTRONIC_CITY.latitude,
            origin_lon=ELECTRONIC_CITY.longitude,
            destination_lat=MAJESTIC.latitude,
            destination_lon=MAJESTIC.longitude,
            departure_time=dep,
        )
    )
    summaries = []
    for j in result.candidates:
        stop_refs = []
        route_refs = []
        for leg in j.legs:
            if leg.from_ref:
                stop_refs.append(leg.from_ref)
            if leg.to_ref:
                stop_refs.append(leg.to_ref)
            if leg.route_id:
                route_refs.append(leg.route_id)
        summaries.append(
            {
                "id": j.candidate_id,
                "modes": list(j.modes),
                "transfer_count": j.transfer_count,
                "walking_meters": j.walking_distance_meters,
                "temporal_feasibility": j.temporal_feasibility,
                "stop_refs": stop_refs,
                "route_refs": route_refs,
                "warnings": list(j.warnings),
            }
        )

    return {
        "departure_time": dep.isoformat(),
        "canonical_demo_departure_was_used": dep == CANONICAL_DEMO_DEPARTURE,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "candidate_count": len(result.candidates),
        "candidate_ids": [j.candidate_id for j in result.candidates],
        "candidate_summary": summaries,
        "warnings": list(result.warnings),
        "snapshot_versions": dict(graph.snapshot_versions),
        "bmtc_version": snap.version if snap else None,
    }


def build_phase6a_audit_report(
    repository: FileStaticMobilityRepository,
    *,
    radius_m: float = DEFAULT_AUDIT_RADIUS_M,
    source_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload, snap = _load_bmtc_payload(repository)
    if snap is None:
        return {
            "error": "NO_ACTIVE_BMTC_SNAPSHOT",
            "limitations": ["Publish BMTC via build_bmtc_sync_pipeline first."],
        }

    stops, routes = _stops_and_routes(payload)
    meta = payload.get("dataset_meta") or {}
    stats = dict(meta.get("statistics") or {})

    ec = find_nearby_stops(stops, routes, ELECTRONIC_CITY, radius_m=radius_m)
    maj = find_nearby_stops(stops, routes, MAJESTIC, radius_m=radius_m)
    connectivity = analyze_bmtc_connectivity(
        routes,
        [s.stop_id for s in ec],
        [s.stop_id for s in maj],
    )
    multimodal = analyze_bmtc_bmrcl_geographic(repository, radius_m=radius_m)
    jb = journey_builder_smoke(repository, radius_m=radius_m)

    area_ec = bool(ec)
    area_maj = bool(maj)
    if stats.get("bounding_box"):
        bb = stats["bounding_box"]
        area_ec = area_ec or (
            bb["min_lat"] <= ELECTRONIC_CITY.latitude <= bb["max_lat"]
            and bb["min_lon"] <= ELECTRONIC_CITY.longitude <= bb["max_lon"]
        )
        area_maj = area_maj or (
            bb["min_lat"] <= MAJESTIC.latitude <= bb["max_lat"]
            and bb["min_lon"] <= MAJESTIC.longitude <= bb["max_lon"]
        )

    limitations = [
        "BMTC feed authority is COMMUNITY_UNOFFICIAL (not BMTC official).",
        "Timetable accuracy may be imperfect (producer caveat).",
        f"Nearby-stop audit radius = {radius_m} m "
        "(SearchLimits.max_walking_access_meters).",
    ]
    if stats.get("compact_snapshot"):
        limitations.append(
            "Published snapshot is compact: bulk stop_times/shapes/trips omitted; "
            "counts retained in dataset_meta.statistics."
        )
    if multimodal.get("bmtc_to_bmrcl_possible") is False:
        limitations.append(str(multimodal.get("reason")))

    report = {
        "phase": "6A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "authority": meta.get("authority") or "COMMUNITY_UNOFFICIAL",
            "mobilitydatabase_id": meta.get("mobilitydatabase_id"),
            "producer_url": meta.get("producer_url"),
            "listing_url": meta.get("listing_url"),
            "feed_version": meta.get("feed_version"),
            "feed_start_date": meta.get("feed_start_date"),
            "feed_end_date": meta.get("feed_end_date"),
            "snapshot_version": snap.version,
            "snapshot_checksum": snap.checksum,
            "retrieved_at": (
                snap.fetched_at.isoformat()
                if hasattr(snap.fetched_at, "isoformat")
                else str(snap.fetched_at)
            ),
            **(source_meta or {}),
        },
        "service_dates": {
            "earliest": stats.get("earliest_service_date") or meta.get("feed_start_date"),
            "latest": stats.get("latest_service_date") or meta.get("feed_end_date"),
        },
        "statistics": stats,
        "geographic": {
            "bounding_box": stats.get("bounding_box"),
            "electronic_city_area_represented": area_ec,
            "majestic_area_represented": area_maj,
        },
        "electronic_city": {
            "anchor": {
                "name": ELECTRONIC_CITY.name,
                "latitude": ELECTRONIC_CITY.latitude,
                "longitude": ELECTRONIC_CITY.longitude,
            },
            "audit_radius_meters": radius_m,
            "nearby_stops": [s.to_dict() for s in ec],
            "nearby_stop_count": len(ec),
            "route_ids": sorted({rid for s in ec for rid in s.route_ids}),
        },
        "majestic": {
            "anchor": {
                "name": MAJESTIC.name,
                "latitude": MAJESTIC.latitude,
                "longitude": MAJESTIC.longitude,
            },
            "audit_radius_meters": radius_m,
            "nearby_stops": [s.to_dict() for s in maj],
            "nearby_stop_count": len(maj),
            "route_ids": sorted({rid for s in maj for rid in s.route_ids}),
        },
        "connectivity": connectivity,
        "journey_builder": {
            "candidate_count": jb["candidate_count"],
            "candidate_summary": jb["candidate_summary"],
            "graph_nodes": jb["graph_nodes"],
            "graph_edges": jb["graph_edges"],
            "departure_time": jb["departure_time"],
            "warnings": jb["warnings"],
            "note": (
                "Journey Builder smoke uses the existing Phase 5C algorithm "
                "unchanged. Zero candidates with MAX_NODES_EXPLORED does not "
                "contradict topology connectivity; it means the bounded search "
                "did not return a path under default limits."
            ),
        },
        "multimodal": {
            "bmtc_to_bmrcl_possible": multimodal.get("bmtc_to_bmrcl_possible"),
            "reason": multimodal.get("reason"),
            "details": multimodal,
        },
        "limitations": limitations,
    }
    return report


def write_audit_report(report: Dict[str, Any], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return out
