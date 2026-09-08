#!/usr/bin/env python3
"""
Phase 6C — publish BMRCL seed + community GTFS coordinates, write connectivity audit.

Example:
  PYTHONPATH=. .venv/bin/python scripts/phase6c_bmrcl_audit.py \\
    --gtfs .tmp_bmrcl_gtfs/bmrcl-gtfs-main/gtfs/bmrcl.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmrcl import build_bmrcl_sync_pipeline
from src.network.ingest.bmrcl_coords import (
    BMRCL_GTFS_SOURCE_URL,
    coordinate_quality_stats,
    geographic_proximity_bmrcl_bmtc,
)


DEFAULT_RADIUS_M = 800.0


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_audit_report(
    repo: FileStaticMobilityRepository,
    *,
    radius_m: float,
    source_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    bmrcl = repo.get_active_snapshot("bmrcl")
    bmtc = repo.get_active_snapshot("bmtc")
    if bmrcl is None:
        return {"error": "NO_ACTIVE_BMRCL_SNAPSHOT"}

    stations = list(bmrcl.payload.get("stations") or [])
    routes = list(bmrcl.payload.get("routes") or [])
    lines_meta = list(bmrcl.payload.get("lines_meta") or [])
    quality = coordinate_quality_stats(stations)
    interchanges = [
        s["id"]
        for s in stations
        if len(s.get("lines") or []) > 1 or (s.get("interchange_station_ids") or [])
    ]

    bmtc_stops = []
    if bmtc is not None:
        bmtc_stops = list(bmtc.payload.get("stops") or [])

    proximity = geographic_proximity_bmrcl_bmtc(
        stations, bmtc_stops, radius_m=radius_m
    )

    return {
        "phase": "6C",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "topology": "bmrcl_official_web_normalized",
            "coordinates": "Vonter BMRCL GTFS (OpenStreetMap-derived)",
            "coordinates_source_type": "community_unofficial",
            "coordinates_source_url": BMRCL_GTFS_SOURCE_URL,
            "snapshot_version": bmrcl.version,
            "snapshot_checksum": bmrcl.checksum,
            "retrieved_at": (
                bmrcl.fetched_at.isoformat()
                if hasattr(bmrcl.fetched_at, "isoformat")
                else str(bmrcl.fetched_at)
            ),
            **(source_meta or {}),
        },
        "station_count": quality["total_stations"],
        "stations_with_coordinates": quality["stations_with_coordinates"],
        "stations_without_coordinates": quality["stations_without_coordinates"],
        "coordinate_coverage_percent": quality["coordinate_coverage_percent"],
        "duplicate_coordinates": quality["duplicate_coordinates"],
        "out_of_bounds_or_invalid_coordinates": quality[
            "out_of_bounds_or_invalid_coordinates"
        ],
        "metro_lines": [r.get("id") for r in routes] or [l.get("id") for l in lines_meta],
        "interchange_station_count": len(interchanges),
        "interchange_station_ids": sorted(interchanges),
        "nearby_bmtc_stop_count": proximity["nearby_bmtc_stop_links"],
        "stations_with_nearby_bmtc_stop": proximity["stations_with_nearby_bmtc_stop"],
        "stations_without_nearby_bmtc_stop": proximity[
            "stations_without_nearby_bmtc_stop"
        ],
        "multimodal": proximity,
        "dataset_meta_enrichment": (bmrcl.payload.get("dataset_meta") or {}).get(
            "coordinate_enrichment"
        ),
        "bmtc_snapshot_present": bmtc is not None,
        "bmtc_snapshot_version": bmtc.version if bmtc else None,
        "limitations": [
            "Coordinate source is COMMUNITY_UNOFFICIAL (not BMRCL official).",
            "Community GTFS timetable approximations are not used.",
            "Geographic proximity ≠ guaranteed pedestrian access.",
            "Unmatched seed stations retain null coordinates.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gtfs",
        type=Path,
        required=True,
        help="Path to Vonter bmrcl.zip or extracted GTFS directory",
    )
    parser.add_argument(
        "--seed",
        type=Path,
        default=Path("data/mobility_network/bmrcl/seed/bmrcl_network_seed.json"),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("data/mobility_network"),
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Snapshot version (default: bmrcl-enriched-YYYYMMDD)",
    )
    parser.add_argument(
        "--radius-m",
        type=float,
        default=DEFAULT_RADIUS_M,
    )
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=Path("data/mobility_network/bmrcl/audit/phase6c_connectivity.json"),
    )
    args = parser.parse_args()

    gtfs = args.gtfs.resolve()
    if not gtfs.exists():
        raise SystemExit(f"GTFS not found: {gtfs}")

    retrieved = datetime.now(timezone.utc)
    version = args.version or f"bmrcl-enriched-{retrieved.strftime('%Y%m%d')}"
    repo = FileStaticMobilityRepository(args.repo_root)
    result = build_bmrcl_sync_pipeline(
        repo, args.seed, gtfs_path=gtfs
    ).run(version=version)
    print(result.to_dict())
    if not result.success:
        raise SystemExit(1)

    report = build_audit_report(
        repo,
        radius_m=args.radius_m,
        source_meta={
            "raw_gtfs_path": str(gtfs),
            "raw_gtfs_sha256": _sha256(gtfs) if gtfs.is_file() else None,
            "raw_gtfs_bytes": gtfs.stat().st_size if gtfs.is_file() else None,
            "seed_path": str(args.seed),
        },
    )
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"audit_written={args.audit_out}")
    print(
        "stations={station_count} with_coords={stations_with_coordinates} "
        "coverage={coordinate_coverage_percent}% nearby_links={nearby_bmtc_stop_count}".format(
            **{
                k: report[k]
                for k in (
                    "station_count",
                    "stations_with_coordinates",
                    "coordinate_coverage_percent",
                    "nearby_bmtc_stop_count",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
