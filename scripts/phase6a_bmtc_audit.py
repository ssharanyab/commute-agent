#!/usr/bin/env python3
"""
Phase 6A — fetch/publish BMTC community GTFS (compact) + write connectivity audit.

Does not commit the raw archive. Expects a local GTFS path (dir or zip).

Example:
  .venv/bin/python scripts/phase6a_bmtc_audit.py \\
      --gtfs /tmp/bmtc-gtfs/gtfs/bmtc.zip
"""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.network.audit.bmtc_connectivity import (
    build_phase6a_audit_report,
    write_audit_report,
)
from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmtc_gtfs import (
    build_bmtc_sync_pipeline,
    list_gtfs_files_present,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_shape_points(gtfs: Path) -> int:
    """Stream-count shapes.txt without loading into the snapshot."""
    import csv
    import io

    if gtfs.is_file() and gtfs.suffix.lower() == ".zip":
        with zipfile.ZipFile(gtfs) as zf:
            names = {n.split("/")[-1]: n for n in zf.namelist()}
            if "shapes.txt" not in names:
                return 0
            with zf.open(names["shapes.txt"]) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8-sig")
                return sum(1 for _ in csv.DictReader(text))
    path = gtfs / "shapes.txt"
    if not path.exists():
        matches = list(gtfs.rglob("shapes.txt"))
        path = matches[0] if matches else path
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gtfs",
        type=Path,
        required=True,
        help="Path to BMTC GTFS directory or zip (community feed)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("data/mobility_network"),
        help="FileStaticMobilityRepository root",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Snapshot version id (default: community-YYYYMMDD)",
    )
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=Path("data/mobility_network/bmtc/audit/phase6a_connectivity.json"),
    )
    args = parser.parse_args()

    gtfs = args.gtfs.resolve()
    if not gtfs.exists():
        raise SystemExit(f"GTFS path not found: {gtfs}")

    retrieved_at = datetime.now(timezone.utc)
    files = list_gtfs_files_present(gtfs)
    archive_path = gtfs if gtfs.is_file() else None
    raw_sha = _sha256_file(archive_path) if archive_path else None
    raw_size = archive_path.stat().st_size if archive_path else None
    shape_pts = _count_shape_points(gtfs)

    version = args.version or f"community-{retrieved_at.strftime('%Y%m%d')}"
    repo = FileStaticMobilityRepository(args.repo_root)
    result = build_bmtc_sync_pipeline(gtfs, repo, compact=True).run(version=version)
    print(result.to_dict())
    if not result.success:
        raise SystemExit(1)

    active = repo.get_active_snapshot("bmtc")
    assert active is not None
    stats = (active.payload.get("dataset_meta") or {}).get("statistics") or {}
    if stats.get("shape_points", -1) < 0:
        stats = dict(stats)
        stats["shape_points"] = shape_pts
        active.payload.setdefault("dataset_meta", {}).setdefault("statistics", {})
        active.payload["dataset_meta"]["statistics"]["shape_points"] = shape_pts

    source_meta = {
        "raw_archive_path": str(gtfs),
        "raw_archive_sha256": raw_sha,
        "raw_archive_bytes": raw_size,
        "gtfs_files_present": {k: v for k, v in files.items() if k != "_extra_txt"},
        "gtfs_extra_txt": files.get("_extra_txt") or [],
        "producer_repo": "https://github.com/Vonter/bmtc-gtfs",
        "mobilitydatabase": "https://mobilitydatabase.org/feeds/gtfs/mdb-2595",
        "provenance_caveat": (
            "COMMUNITY / UNOFFICIAL — not BMTC official GTFS; "
            "sourced by producer from Namma BMTC app."
        ),
        "normalized_snapshot_path": str(
            Path(args.repo_root) / "bmtc" / "snapshots" / f"{version}.json"
        ),
        "compact_publish": True,
        "shape_points_stream_counted": shape_pts,
    }

    report = build_phase6a_audit_report(repo, source_meta=source_meta)
    # Ensure statistics reflect stream-counted shapes
    if report.get("statistics", {}).get("shape_points", -1) < 0:
        report["statistics"]["shape_points"] = shape_pts
    out = write_audit_report(report, args.audit_out)
    print(f"audit_written={out}")
    print(
        "connectivity={}".format(report.get("connectivity", {}).get("result")),
        "jb_candidates={}".format(
            report.get("journey_builder", {}).get("candidate_count")
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
