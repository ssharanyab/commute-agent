#!/usr/bin/env python3
"""
Phase 6D — candidate connectivity audit (what the builder actually discovers).

Does not hardcode journey templates. OD pairs are audit fixtures only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest, SearchLimits
from src.journey_builder.graph import build_mobility_graph
from src.network.file_repository import FileStaticMobilityRepository


def _classify(journey) -> List[str]:
    tags: List[str] = []
    modes = set(journey.modes)
    if modes <= {"walk"}:
        tags.append("walk_only")
    if modes & {"bus"} and not (modes & {"metro", "cab", "auto_rickshaw"}):
        tags.append("bmtc")
    if "metro" in modes and not (modes & {"bus", "cab", "auto_rickshaw"}):
        tags.append("metro")
    if "metro" in modes:
        tags.append("metro_containing")
    if "bus" in modes and "metro" in modes:
        tags.append("bmtc_metro_multimodal")
    if "auto_rickshaw" in modes:
        tags.append("auto_containing")
    if "cab" in modes:
        tags.append("cab_containing")
    if modes <= {"cab"} or modes <= {"auto_rickshaw"} or modes <= {"cab", "auto_rickshaw"}:
        tags.append("road_only")
    if journey.road_leg_count and not journey.transit_leg_count:
        tags.append("road_only_structural")
    if len(modes) > 1:
        tags.append("multimodal")
    if any(
        getattr(l, "segment_role", None)
        and l.segment_role.value == "full_journey_road"
        for l in journey.legs
    ):
        tags.append("full_journey_road_role")
    return tags


def _extra_audit_ods() -> List[Tuple[str, float, float, float, float]]:
    """
    Additional real OD fixtures near published BMRCL stations with BMTC proximity.
    Audit-only — never used by production search templates.
    """
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


def audit_od(
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
    tag_counter: Counter = Counter()
    signatures: List[str] = []
    for j in result.candidates:
        signatures.append(j.mode_signature or " → ".join(j.modes))
        for t in _classify(j):
            tag_counter[t] += 1

    meta = result.search_metadata
    return {
        "origin_label": label.split("→")[0].strip() if "→" in label else label,
        "destination_label": label.split("→")[-1].strip() if "→" in label else "",
        "label": label,
        "origin": [olat, olon],
        "destination": [dlat, dlon],
        "candidate_count": len(result.candidates),
        "mode_signatures": signatures,
        "categories": dict(tag_counter),
        "warnings": list(result.warnings),
        "search_statistics": {
            "algorithm": meta.get("algorithm"),
            "nodes_explored": meta.get("nodes_explored"),
            "edges_considered": meta.get("edges_considered"),
            "candidates_generated": meta.get("candidates_generated"),
            "candidates_pruned": meta.get("candidates_pruned"),
            "candidates_trimmed": meta.get("candidates_trimmed"),
            "search_termination_reason": meta.get("search_termination_reason"),
            "max_depth_reached": meta.get("max_depth_reached"),
            "origin_access_count": meta.get("origin_access_count"),
            "destination_access_count": meta.get("destination_access_count"),
            "max_nodes_explored_limit": limits.max_nodes_explored,
            "max_candidates_limit": limits.max_candidates,
        },
        "pruning": {
            "dominance_or_worse_partials": meta.get("candidates_pruned"),
            "termination": meta.get("search_termination_reason"),
            "node_cap_hit": "MAX_NODES_EXPLORED" in result.warnings,
            "no_path": "NO_PATH_FOUND" in result.warnings,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("data/mobility_network"))
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=Path("data/mobility_network/audit/phase6d_candidates.json"),
    )
    args = parser.parse_args()

    repo = FileStaticMobilityRepository(args.repo_root)
    if repo.get_active_snapshot("bmtc") is None:
        raise SystemExit("Need published BMTC snapshot (Phase 6A)")
    builder = DynamicJourneyBuilder(repo)
    departure = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)

    limit_sets = {
        "road_access_on": SearchLimits(
            allow_road_access=True,
            allow_direct_road=True,
            max_candidates=20,
            max_nodes_explored=5000,
        ),
        "road_access_off": SearchLimits(
            allow_road_access=False,
            allow_direct_road=False,
            max_candidates=20,
            max_nodes_explored=5000,
        ),
        "road_access_on_cap100": SearchLimits(
            allow_road_access=True,
            allow_direct_road=True,
            max_candidates=100,
            max_nodes_explored=5000,
        ),
    }

    base_ods = [
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
    ] + list(_extra_audit_ods())

    graph = build_mobility_graph(repo)
    xfer = sum(1 for e in graph.edges.values() if e.kind.value == "transfer_walk")

    reports: List[Dict[str, Any]] = []
    for limit_name, limits in limit_sets.items():
        for label, olat, olon, dlat, dlon in base_ods:
            # Cap100 only for canonical EC↔Majestic (cost control).
            if limit_name == "road_access_on_cap100" and "Electronic City" not in label:
                continue
            row = audit_od(
                builder,
                label=f"{label} [{limit_name}]",
                olat=olat,
                olon=olon,
                dlat=dlat,
                dlon=dlon,
                departure=departure,
                limits=limits,
            )
            row["limit_profile"] = limit_name
            reports.append(row)

    out = {
        "phase": "6D",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "transfer_walk_edges": xfer,
            "snapshot_versions": dict(graph.snapshot_versions),
        },
        "search_limit_profiles": {k: v.to_dict() for k, v in limit_sets.items()},
        "od_audits": reports,
        "notes": [
            "Mode signatures are audit representations, not generation templates.",
            "Categories are non-exclusive tags.",
            "Dominance key includes mode sequence so walk/auto/cab variants are not collapsed.",
            "candidate_cap often fills with road+bus before metro under road_access_on.",
        ],
    }
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"audit_written={args.audit_out}")
    for r in reports:
        print(
            r["label"],
            "candidates=",
            r["candidate_count"],
            "cats=",
            r["categories"],
            "term=",
            r["search_statistics"]["search_termination_reason"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
