"""Shared helpers for Phase 5B ingest adapters."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from src.network.models import DataProvenance, SourceType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_gtfs_table(gtfs_root: Path, filename: str) -> List[Dict[str, str]]:
    """Load a GTFS CSV table from a directory or .zip archive. Empty if missing."""
    path = gtfs_root / filename
    if gtfs_root.is_file() and gtfs_root.suffix.lower() == ".zip":
        with zipfile.ZipFile(gtfs_root) as zf:
            names = {n.split("/")[-1]: n for n in zf.namelist()}
            if filename not in names:
                return []
            with zf.open(names[filename]) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8-sig")
                return list(csv.DictReader(text))
    if not path.exists():
        # Also allow nested single-folder zip extracts
        matches = list(gtfs_root.rglob(filename))
        if not matches:
            return []
        path = matches[0]
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def community_bmtc_provenance(
    *,
    retrieved_at: Optional[datetime] = None,
    version: Optional[str] = None,
    feed_start: Optional[str] = None,
    feed_end: Optional[str] = None,
) -> DataProvenance:
    notes = (
        "COMMUNITY / UNOFFICIAL BMTC GTFS (MobilityDatabase mdb-2595; "
        "producer Vonter/bmtc-gtfs). Source described by producer as derived "
        "from the Namma BMTC app; timetable accuracy may be imperfect. "
        "NOT BMTC official GTFS."
    )
    if feed_start or feed_end:
        notes += f" Feed info dates: start={feed_start or 'n/a'} end={feed_end or 'n/a'}."
    return DataProvenance(
        source="bmtc_gtfs_community_vonter",
        source_type=SourceType.COMMUNITY_UNOFFICIAL,
        retrieved_at=retrieved_at or utc_now(),
        version=version,
        confidence=0.55,
        quality_notes="Unofficial community GTFS; schedules may be incomplete or inaccurate.",
        source_url="https://github.com/Vonter/bmtc-gtfs",
        notes=notes,
    )


def bmrcl_official_derived_provenance(
    *,
    retrieved_at: Optional[datetime] = None,
    version: str = "seed-2024",
) -> DataProvenance:
    return DataProvenance(
        source="bmrcl_official_web_normalized",
        source_type=SourceType.OFFICIAL_OPEN_DATA,
        retrieved_at=retrieved_at or utc_now(),
        version=version,
        confidence=0.8,
        quality_notes=(
            "Normalized/derived station and line ordering from BMRCL official "
            "schematic/route information. Coordinates omitted unless an "
            "official machine-readable source provides them."
        ),
        source_url="https://english.bmrc.co.in/schematic-route-map/",
        notes=(
            "Derived from official BMRCL website materials "
            "(https://english.bmrc.co.in/). Not a downloadable official GTFS feed."
        ),
    )


def auto_fare_provenance(
    *,
    retrieved_at: Optional[datetime] = None,
    version: str = "rta-notified-structure",
) -> DataProvenance:
    return DataProvenance(
        source="bengaluru_rta_auto_fare_regulated",
        source_type=SourceType.GOVERNMENT_REGULATED,
        retrieved_at=retrieved_at or utc_now(),
        version=version,
        confidence=0.85,
        quality_notes=(
            "Regulated auto-rickshaw fare estimate for Bengaluru. "
            "Not Uber/Ola/Rapido/Namma Yatri live pricing."
        ),
        source_url=(
            "https://transport.karnataka.gov.in/"
        ),
        notes=(
            "Structure reflects Bengaluru RTA / government-notified auto fare "
            "revision as commonly published (₹36 first 2 km; ₹18/km thereafter; "
            "1.5× night 22:00–05:00). Primary gazette URL may vary by revision; "
            "transport.karnataka.gov.in recorded as institutional authority hub."
        ),
    )


def shakti_provenance(
    *,
    retrieved_at: Optional[datetime] = None,
    version: str = "shakti-gov-docs",
) -> DataProvenance:
    return DataProvenance(
        source="karnataka_shakti_scheme",
        source_type=SourceType.OFFICIAL_OPEN_DATA,
        retrieved_at=retrieved_at or utc_now(),
        version=version,
        confidence=0.9,
        quality_notes=(
            "Official government scheme documentation. Eligibility must be "
            "evaluated explicitly; do not assume from incomplete passenger profiles."
        ),
        source_url="https://bengaluruurban.nic.in/en/scheme-category/transport-department/",
        notes=(
            "Supporting research: "
            "https://fpibengaluru.karnataka.gov.in/storage/pdf-files/Technical%20Reports/"
            "FinalcopyofFiscaleffectsofShaktiScheme_04072024.pdf"
        ),
    )
