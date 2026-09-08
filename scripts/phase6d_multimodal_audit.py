#!/usr/bin/env python3
"""
Phase 6D — multimodal candidate diversity audit (real BMTC + BMRCL data).

AUDIT → diagnose generated vs pruned vs cap-trimmed. OD pairs are fixtures only.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest, SearchLimits
from src.journey_builder.diversity import audit_mode_signature, transit_pattern
from src.journey_builder.graph import build_mobility_graph
from src.journey_builder.models import EdgeKind, SegmentRole
from src.network.file_repository import FileStaticMobilityRepository


def _extra_ods() -> List[Tuple[str, float, float, float, float]]:
    """Audit fixtures near real metro corridors — not production templates."""
    return [
        (
            "Indiranagar → Nadaprabhu Kempegowda (Majestic)",
            12.978333,
            77.638664,
            12.975708,
            77.572876,
        ),
        (
            "Jayanagar → Nadaprabhu Kempegowda (Majestic)",
            12.929507,
            77.58015,
            12.975708,
            77.572876,
        ),
        (
            "Central Silk Board → Indiranagar",
            12.916582,
            77.62057,
            12.978333,
            77.638664,
        ),
    ]


def _classify(journey) -> Dict[str, bool]:
    modes = set(journey.modes)
    sig = audit_mode_signature(journey.modes)
    tokens = [t.strip() for t in sig.split("→")]
    has_road_direct = any(
        getattr(l, "segment_role", None) == SegmentRole.FULL_JOURNEY_ROAD
        or l.edge_kind == EdgeKind.ROAD_DIRECT
        for l in journey.legs
    )
    metro_legs = sum(1 for l in journey.legs if l.mode.value == "metro")
    return {
        "bmtc_containing": "bus" in modes,
        "metro_containing": "metro" in modes,
        "bmtc_metro": "bus" in modes and "metro" in modes,
        "metro_only_transit": "metro" in modes and "bus" not in modes,
        "bmtc_only_transit": "bus" in modes and "metro" not in modes,
        "auto_containing": "auto_rickshaw" in modes,
        "cab_containing": "cab" in modes,
        "road_direct": has_road_direct,
        "walking": "walk" in modes,
        "multimodal": len(modes) > 1,
        "metro_metro": metro_legs >= 2
        or (metro_legs >= 1 and "metro → metro" in sig.replace(" ", "")),
    }


def audit_one(
    builder: DynamicJourneyBuilder,
    *,
    label: str,
    olat: float,
    olon: float,
    dlat: float,
    dlon: float,
    departure: datetime,
    limits: SearchLimits,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    result = builder.build(
        JourneyBuildRequest(
            origin_lat=olat,
            origin_lon=olon,
            destination_lat=dlat,
            destination_lon=dlon,
            departure_time=departure,
            search_limits=limits,
        )
    )
    elapsed = time.perf_counter() - t0
    meta = result.search_metadata

    sigs: List[str] = []
    cats = Counter()
    legs_dist: List[int] = []
    xfer_dist: List[int] = []
    walk_dist: List[float] = []
    dur_dist: List[float] = []

    for j in result.candidates:
        sig = audit_mode_signature(j.modes)
        sigs.append(sig)
        flags = _classify(j)
        for k, v in flags.items():
            if v:
                cats[k] += 1
        legs_dist.append(len(j.legs))
        xfer_dist.append(j.transfer_count)
        walk_dist.append(j.walking_distance_meters)
        if j.total_duration_seconds is not None:
            dur_dist.append(j.total_duration_seconds)

    gen_sigs = meta.get("generated_mode_signatures") or []
    metro_gen = int(meta.get("metro_containing_generated") or 0)
    metro_ret = cats["metro_containing"]

    diagnosis = "unknown"
    if metro_ret > 0:
        diagnosis = "D_retained_available"
    elif metro_gen > 0:
        diagnosis = "C_generated_but_cap_or_diversity_trimmed"
    elif meta.get("search_termination_reason") == "max_nodes_explored":
        diagnosis = "A_or_B_not_in_pool_node_limit"
    else:
        diagnosis = "A_never_generated_in_collection_window"

    return {
        "label": label,
        "origin": [olat, olon],
        "destination": [dlat, dlon],
        "elapsed_seconds": round(elapsed, 3),
        "candidate_count": len(result.candidates),
        "unique_mode_signatures": sorted(set(sigs)),
        "unique_signature_count": len(set(sigs)),
        "mode_signatures": sigs,
        "categories": dict(cats),
        "distributions": {
            "legs": {
                "min": min(legs_dist) if legs_dist else None,
                "max": max(legs_dist) if legs_dist else None,
                "mean": round(sum(legs_dist) / len(legs_dist), 2) if legs_dist else None,
            },
            "transfers": {
                "min": min(xfer_dist) if xfer_dist else None,
                "max": max(xfer_dist) if xfer_dist else None,
                "mean": round(sum(xfer_dist) / len(xfer_dist), 2) if xfer_dist else None,
            },
            "walking_meters": {
                "min": min(walk_dist) if walk_dist else None,
                "max": max(walk_dist) if walk_dist else None,
                "mean": round(sum(walk_dist) / len(walk_dist), 2) if walk_dist else None,
            },
            "duration_seconds_known": {
                "count": len(dur_dist),
                "mean": round(sum(dur_dist) / len(dur_dist), 2) if dur_dist else None,
            },
        },
        "pruning": {
            "nodes_explored": meta.get("nodes_explored"),
            "edges_considered": meta.get("edges_considered"),
            "candidates_generated": meta.get("candidates_generated"),
            "candidates_retained": meta.get("candidates_retained"),
            "candidate_cap_pruned": meta.get("candidate_cap_pruned"),
            "dominance_pruned": meta.get("dominance_pruned"),
            "constraint_pruned": meta.get("constraint_pruned"),
            "leg_limit_pruned": meta.get("leg_limit_pruned"),
            "node_limit_pruned": meta.get("node_limit_pruned"),
            "duplicate_signature_skipped": meta.get("duplicate_signature_skipped"),
            "dest_reaches": meta.get("dest_reaches"),
            "search_termination_reason": meta.get("search_termination_reason"),
        },
        "generated_vs_retained": {
            "generated_mode_signatures": gen_sigs,
            "generated_signature_counts": meta.get("generated_signature_counts"),
            "metro_containing_generated": metro_gen,
            "metro_containing_retained": metro_ret,
            "transit_patterns_generated": meta.get("transit_patterns_generated"),
            "diagnosis": diagnosis,
        },
        "diversity": meta.get("diversity"),
        "warnings": list(result.warnings),
        "limits": limits.to_dict(),
    }


def cap_sweep(
    builder: DynamicJourneyBuilder,
    *,
    label: str,
    olat: float,
    olon: float,
    dlat: float,
    dlon: float,
    departure: datetime,
    road: bool,
    caps: List[int],
) -> List[Dict[str, Any]]:
    rows = []
    for cap in caps:
        limits = SearchLimits(
            allow_road_access=road,
            allow_direct_road=road,
            max_candidates=cap,
            max_nodes_explored=5000,
        )
        row = audit_one(
            builder,
            label=f"{label} [cap={cap}, road={road}]",
            olat=olat,
            olon=olon,
            dlat=dlat,
            dlon=dlon,
            departure=departure,
            limits=limits,
        )
        rows.append(
            {
                "candidate_cap": cap,
                "road_access": road,
                "candidate_count": row["candidate_count"],
                "metro_containing": row["categories"].get("metro_containing", 0),
                "bmtc_metro": row["categories"].get("bmtc_metro", 0),
                "metro_metro": row["categories"].get("metro_metro", 0),
                "road_direct": row["categories"].get("road_direct", 0),
                "unique_signatures": row["unique_signature_count"],
                "signatures": row["unique_mode_signatures"],
                "nodes_explored": row["pruning"]["nodes_explored"],
                "dest_reaches": row["pruning"]["dest_reaches"],
                "termination": row["pruning"]["search_termination_reason"],
                "elapsed_seconds": row["elapsed_seconds"],
                "diagnosis": row["generated_vs_retained"]["diagnosis"],
                "metro_generated": row["generated_vs_retained"][
                    "metro_containing_generated"
                ],
            }
        )
    return rows


def metro_topology_notes(repo: FileStaticMobilityRepository) -> Dict[str, Any]:
    snap = repo.get_active_snapshot("bmrcl")
    if not snap:
        return {}
    stations = snap.payload.get("stations") or []
    routes = snap.payload.get("routes") or []
    lines = sorted(
        {
            ln
            for s in stations
            for ln in (s.get("lines") or [])
        }
    )
    interchange = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "lines": s.get("lines"),
        }
        for s in stations
        if len(s.get("lines") or []) > 1 or s.get("interchange_station_ids")
    ]
    return {
        "station_count": len(stations),
        "stations_with_coords": sum(
            1
            for s in stations
            if s.get("latitude") is not None and s.get("longitude") is not None
        ),
        "routes": [
            {"id": r.get("id"), "name": r.get("name"), "stops": len(r.get("stop_ids") or [])}
            for r in routes
        ],
        "lines": lines,
        "interchange_stations": interchange,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("data/mobility_network"))
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=Path("data/mobility_network/audit/phase6d_multimodal.json"),
    )
    parser.add_argument("--quick", action="store_true", help="Skip large cap sweeps")
    args = parser.parse_args()

    repo = FileStaticMobilityRepository(args.repo_root)
    if repo.get_active_snapshot("bmtc") is None:
        raise SystemExit("Need published BMTC snapshot (Phase 6A)")
    if repo.get_active_snapshot("bmrcl") is None:
        raise SystemExit("Need published BMRCL snapshot (Phase 6C)")

    builder = DynamicJourneyBuilder(repo)
    departure = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
    graph = build_mobility_graph(repo)
    xfer = sum(1 for e in graph.edges.values() if e.kind.value == "transfer_walk")

    ods = [
        (
            "Electronic City → Majestic",
            ELECTRONIC_CITY.latitude,
            ELECTRONIC_CITY.longitude,
            MAJESTIC.latitude,
            MAJESTIC.longitude,
        ),
        (
            "Majestic → Electronic City",
            MAJESTIC.latitude,
            MAJESTIC.longitude,
            ELECTRONIC_CITY.latitude,
            ELECTRONIC_CITY.longitude,
        ),
    ] + list(_extra_ods())

    default_limits = SearchLimits(
        allow_road_access=True,
        allow_direct_road=True,
        max_candidates=20,
        max_nodes_explored=5000,
    )
    od_reports = [
        audit_one(
            builder,
            label=label,
            olat=olat,
            olon=olon,
            dlat=dlat,
            dlon=dlon,
            departure=departure,
            limits=default_limits,
        )
        for label, olat, olon, dlat, dlon in ods
    ]

    # Also road-off baseline for EC↔Majestic
    for label, olat, olon, dlat, dlon in ods[:2]:
        od_reports.append(
            audit_one(
                builder,
                label=f"{label} [road_access_off]",
                olat=olat,
                olon=olon,
                dlat=dlat,
                dlon=dlon,
                departure=departure,
                limits=SearchLimits(
                    allow_road_access=False,
                    allow_direct_road=False,
                    max_candidates=20,
                    max_nodes_explored=5000,
                ),
            )
        )

    sweeps: Dict[str, Any] = {}
    if not args.quick:
        caps = [10, 20, 50, 100, 200]
        for road in (True, False):
            key = f"Electronic City → Majestic road={road}"
            sweeps[key] = cap_sweep(
                builder,
                label="Electronic City → Majestic",
                olat=ELECTRONIC_CITY.latitude,
                olon=ELECTRONIC_CITY.longitude,
                dlat=MAJESTIC.latitude,
                dlon=MAJESTIC.longitude,
                departure=departure,
                road=road,
                caps=caps,
            )

    out = {
        "phase": "6D_multimodal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "transfer_walk_edges": xfer,
            "snapshot_versions": dict(graph.snapshot_versions),
        },
        "metro_topology": metro_topology_notes(repo),
        "od_audits": od_reports,
        "candidate_cap_sweeps": sweeps,
        "notes": [
            "Signatures are audit-only (bus normalized to bmtc).",
            "Diagnosis codes: A never generated, B pruned, C cap-trimmed, D retained.",
            "No journey templates; search remains graph-driven.",
        ],
    }
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"audit_written={args.audit_out}")
    for r in od_reports:
        print(
            r["label"],
            "n=",
            r["candidate_count"],
            "metro_ret=",
            r["categories"].get("metro_containing", 0),
            "metro_gen=",
            r["generated_vs_retained"]["metro_containing_generated"],
            "diag=",
            r["generated_vs_retained"]["diagnosis"],
            "t=",
            r["elapsed_seconds"],
            "sigs=",
            r["unique_signature_count"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
