"""
BMRCL geographic enrichment from Vonter community GTFS (OSM-derived coords).

Topology provenance remains OFFICIAL (seed). Coordinate provenance is always
COMMUNITY_UNOFFICIAL and is stored separately under source_metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.network.ingest import blank_to_none, read_gtfs_table, utc_now
from src.network.models import SourceType


BMRCL_GTFS_SOURCE_URL = "https://github.com/Vonter/bmrcl-gtfs"
BMRCL_GTFS_SOURCE_NAME = "Vonter BMRCL GTFS"
BMRCL_COORDINATE_SOURCE = "OpenStreetMap-derived"

# Bengaluru metro operating area (inclusive). Used for sanity validation only.
BENGALURU_LAT_BOUNDS = (12.70, 13.25)
BENGALURU_LON_BOUNDS = (77.35, 77.85)

DEFAULT_ALIAS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "mobility_network"
    / "bmrcl"
    / "enrichment"
    / "station_id_aliases.json"
)


def normalize_station_name(name: str) -> str:
    """Deterministic name key for exact matching (not fuzzy)."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for tok in ("station", "stn", "metro", "namma metro"):
        s = re.sub(rf"\b{tok}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def community_bmrcl_coordinate_provenance(
    *,
    retrieved_at: Optional[datetime] = None,
    version: Optional[str] = None,
    gtfs_stop_id: Optional[str] = None,
    match_method: Optional[str] = None,
    checksum: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "source_type": SourceType.COMMUNITY_UNOFFICIAL.value,
        "source_name": BMRCL_GTFS_SOURCE_NAME,
        "source_url": BMRCL_GTFS_SOURCE_URL,
        "coordinate_source": BMRCL_COORDINATE_SOURCE,
        "retrieved_at": (retrieved_at or utc_now()).isoformat(),
        "version": version,
        "gtfs_stop_id": gtfs_stop_id,
        "match_method": match_method,
        "raw_checksum": checksum,
        "notes": (
            "COMMUNITY / UNOFFICIAL coordinates from Vonter/bmrcl-gtfs "
            "(OpenStreetMap-derived spatial data). NOT official BMRCL coordinates. "
            "Timetables in that feed are approximate and are NOT used here."
        ),
    }


@dataclass
class GtfsStationCoord:
    stop_id: str
    stop_name: str
    latitude: float
    longitude: float


@dataclass
class MatchResult:
    station_id: str
    status: str  # matched | unmatched | ambiguous | invalid_coordinate
    method: Optional[str] = None
    gtfs_stop_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    detail: Optional[str] = None


@dataclass
class EnrichmentReport:
    total_stations: int = 0
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    invalid_coordinate: int = 0
    results: List[MatchResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_stations": self.total_stations,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "ambiguous": self.ambiguous,
            "invalid_coordinate": self.invalid_coordinate,
            "results": [r.__dict__ for r in self.results],
        }


def load_alias_map(path: Path | str = DEFAULT_ALIAS_PATH) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    aliases = raw.get("aliases") or {}
    return {str(k): str(v) for k, v in aliases.items()}


def load_gtfs_station_coordinates(gtfs_path: Path | str) -> Dict[str, GtfsStationCoord]:
    """Load location_type=1 stations from a GTFS dir/zip. Platforms/entrances skipped."""
    rows = read_gtfs_table(Path(gtfs_path), "stops.txt")
    out: Dict[str, GtfsStationCoord] = {}
    for row in rows:
        loc = blank_to_none(row.get("location_type")) or "0"
        if loc != "1":
            continue
        stop_id = blank_to_none(row.get("stop_id"))
        name = blank_to_none(row.get("stop_name"))
        lat_s = blank_to_none(row.get("stop_lat"))
        lon_s = blank_to_none(row.get("stop_lon"))
        if not stop_id or not name or lat_s is None or lon_s is None:
            continue
        out[stop_id] = GtfsStationCoord(
            stop_id=stop_id,
            stop_name=name,
            latitude=float(lat_s),
            longitude=float(lon_s),
        )
    return out


def file_sha256(path: Path | str) -> Optional[str]:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _in_bengaluru_bounds(lat: float, lon: float) -> bool:
    return (
        BENGALURU_LAT_BOUNDS[0] <= lat <= BENGALURU_LAT_BOUNDS[1]
        and BENGALURU_LON_BOUNDS[0] <= lon <= BENGALURU_LON_BOUNDS[1]
    )


def validate_coordinate_pair(
    lat: Optional[float], lon: Optional[float]
) -> List[str]:
    """Return error codes; empty means OK (including both-null)."""
    if lat is None and lon is None:
        return []
    if lat is None or lon is None:
        return ["PARTIAL_COORDINATES"]
    if lat == 0.0 and lon == 0.0:
        return ["ZERO_COORDINATE"]
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return ["GLOBAL_BOUNDS"]
    if not _in_bengaluru_bounds(lat, lon):
        return ["OUT_OF_BENGALURU_BOUNDS"]
    return []


def match_station_coordinate(
    station_id: str,
    station_name: str,
    gtfs_by_id: Dict[str, GtfsStationCoord],
    gtfs_by_norm_name: Dict[str, List[GtfsStationCoord]],
    aliases: Dict[str, str],
) -> MatchResult:
    # 1) stable alias: seed id → gtfs stop_id
    alias_gtfs_id = aliases.get(station_id)
    if alias_gtfs_id:
        hit = gtfs_by_id.get(alias_gtfs_id)
        if hit is None:
            return MatchResult(
                station_id=station_id,
                status="unmatched",
                method="alias_id",
                detail=f"alias points to missing gtfs id {alias_gtfs_id}",
            )
        errs = validate_coordinate_pair(hit.latitude, hit.longitude)
        if errs:
            return MatchResult(
                station_id=station_id,
                status="invalid_coordinate",
                method="alias_id",
                gtfs_stop_id=hit.stop_id,
                latitude=hit.latitude,
                longitude=hit.longitude,
                detail=",".join(errs),
            )
        return MatchResult(
            station_id=station_id,
            status="matched",
            method="alias_id",
            gtfs_stop_id=hit.stop_id,
            latitude=hit.latitude,
            longitude=hit.longitude,
        )

    # 2) exact normalized name
    key = normalize_station_name(station_name)
    candidates = gtfs_by_norm_name.get(key) or []
    if len(candidates) == 1:
        hit = candidates[0]
        errs = validate_coordinate_pair(hit.latitude, hit.longitude)
        if errs:
            return MatchResult(
                station_id=station_id,
                status="invalid_coordinate",
                method="exact_normalized_name",
                gtfs_stop_id=hit.stop_id,
                latitude=hit.latitude,
                longitude=hit.longitude,
                detail=",".join(errs),
            )
        return MatchResult(
            station_id=station_id,
            status="matched",
            method="exact_normalized_name",
            gtfs_stop_id=hit.stop_id,
            latitude=hit.latitude,
            longitude=hit.longitude,
        )
    if len(candidates) > 1:
        return MatchResult(
            station_id=station_id,
            status="ambiguous",
            method="exact_normalized_name",
            detail=f"{len(candidates)} GTFS stations share normalized name '{key}'",
        )

    return MatchResult(
        station_id=station_id,
        status="unmatched",
        method=None,
        detail="no exact id alias or normalized name match",
    )


def enrich_stations_with_gtfs_coordinates(
    stations: List[dict],
    gtfs_path: Path | str,
    *,
    alias_path: Path | str = DEFAULT_ALIAS_PATH,
    retrieved_at: Optional[datetime] = None,
    feed_version: Optional[str] = None,
) -> Tuple[List[dict], EnrichmentReport, Dict[str, Any]]:
    """
    Apply community GTFS coordinates onto normalized station dicts.

    Topology provenance on each station is left unchanged.
    Invalid matched coordinates raise via report status; caller validates.
    Ambiguous / unmatched → coordinates remain null.
    """
    retrieved = retrieved_at or utc_now()
    gtfs = load_gtfs_station_coordinates(gtfs_path)
    aliases = load_alias_map(alias_path)
    by_name: Dict[str, List[GtfsStationCoord]] = {}
    for coord in gtfs.values():
        by_name.setdefault(normalize_station_name(coord.stop_name), []).append(coord)

    checksum = file_sha256(gtfs_path)
    # Prefer zip checksum when path is a directory beside a known zip.
    report = EnrichmentReport(total_stations=len(stations))
    out: List[dict] = []

    for raw in stations:
        st = dict(raw)
        sid = str(st["id"])
        name = str(st.get("name") or sid)
        match = match_station_coordinate(sid, name, gtfs, by_name, aliases)
        report.results.append(match)

        meta = dict(st.get("source_metadata") or {})
        # Never claim coordinates are official.
        meta.pop("coordinates_verified_official", None)

        if match.status == "matched":
            report.matched += 1
            st["latitude"] = match.latitude
            st["longitude"] = match.longitude
            meta["coordinate_provenance"] = community_bmrcl_coordinate_provenance(
                retrieved_at=retrieved,
                version=feed_version,
                gtfs_stop_id=match.gtfs_stop_id,
                match_method=match.method,
                checksum=checksum,
            )
            meta["coordinate_confidence"] = 0.7
            meta["coordinate_authority"] = "COMMUNITY_UNOFFICIAL"
        elif match.status == "ambiguous":
            report.ambiguous += 1
            st["latitude"] = None
            st["longitude"] = None
            meta["coordinate_match_status"] = "ambiguous"
            meta["coordinate_match_detail"] = match.detail
        elif match.status == "invalid_coordinate":
            report.invalid_coordinate += 1
            # Do not attach bad coordinates; surface via validation.
            st["latitude"] = match.latitude
            st["longitude"] = match.longitude
            meta["coordinate_match_status"] = "invalid_coordinate"
            meta["coordinate_match_detail"] = match.detail
            meta["coordinate_provenance"] = community_bmrcl_coordinate_provenance(
                retrieved_at=retrieved,
                version=feed_version,
                gtfs_stop_id=match.gtfs_stop_id,
                match_method=match.method,
                checksum=checksum,
            )
        else:
            report.unmatched += 1
            st["latitude"] = None
            st["longitude"] = None
            meta["coordinate_match_status"] = "unmatched"
            meta["coordinate_match_detail"] = match.detail

        st["source_metadata"] = meta
        out.append(st)

    enrichment_meta = {
        "coordinate_enrichment": {
            "enabled": True,
            "source_name": BMRCL_GTFS_SOURCE_NAME,
            "source_url": BMRCL_GTFS_SOURCE_URL,
            "coordinate_source": BMRCL_COORDINATE_SOURCE,
            "source_type": SourceType.COMMUNITY_UNOFFICIAL.value,
            "gtfs_path": str(gtfs_path),
            "raw_checksum": checksum,
            "retrieved_at": retrieved.isoformat(),
            "feed_version": feed_version,
            "report": {
                "matched": report.matched,
                "unmatched": report.unmatched,
                "ambiguous": report.ambiguous,
                "invalid_coordinate": report.invalid_coordinate,
                "total_stations": report.total_stations,
            },
            "notes": (
                "Coordinates enriched from community GTFS; topology provenance "
                "remains official/normalized seed. Do not treat GTFS times as authoritative."
            ),
        }
    }
    return out, report, enrichment_meta


def coordinate_quality_stats(stations: List[dict]) -> Dict[str, Any]:
    total = len(stations)
    with_coords = 0
    without = 0
    duplicate_coords: Dict[Tuple[float, float], List[str]] = {}
    out_of_bounds = 0
    for st in stations:
        lat, lon = st.get("latitude"), st.get("longitude")
        if lat is None or lon is None:
            without += 1
            continue
        with_coords += 1
        key = (round(float(lat), 6), round(float(lon), 6))
        duplicate_coords.setdefault(key, []).append(str(st.get("id")))
        if validate_coordinate_pair(float(lat), float(lon)):
            out_of_bounds += 1
    dupes = {f"{k[0]},{k[1]}": v for k, v in duplicate_coords.items() if len(v) > 1}
    return {
        "total_stations": total,
        "stations_with_coordinates": with_coords,
        "stations_without_coordinates": without,
        "coordinate_coverage_percent": round(
            (100.0 * with_coords / total) if total else 0.0, 2
        ),
        "duplicate_coordinates": dupes,
        "out_of_bounds_or_invalid_coordinates": out_of_bounds,
    }


def geographic_proximity_bmrcl_bmtc(
    bmrcl_stations: List[dict],
    bmtc_stops: List[dict],
    *,
    radius_m: float,
) -> Dict[str, Any]:
    """Geographic proximity audit only — not proven walkability."""
    import math

    def _hav(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = (
            math.sin(dp / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        )
        return 2 * r * math.asin(math.sqrt(a))

    stations_with = [
        s
        for s in bmrcl_stations
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    stops_with = [
        s
        for s in bmtc_stops
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    nearby_pairs = 0
    stations_with_nearby = 0
    stations_without_nearby: List[str] = []
    for st in stations_with:
        hit = False
        for stop in stops_with:
            d = _hav(
                float(st["latitude"]),
                float(st["longitude"]),
                float(stop["latitude"]),
                float(stop["longitude"]),
            )
            if d <= radius_m:
                nearby_pairs += 1
                hit = True
        if hit:
            stations_with_nearby += 1
        else:
            stations_without_nearby.append(str(st["id"]))

    return {
        "relationship": "geographic_proximity",
        "audit_radius_meters": radius_m,
        "bmrcl_stations_with_coordinates": len(stations_with),
        "bmtc_stops_with_coordinates": len(stops_with),
        "nearby_bmtc_stop_links": nearby_pairs,
        "stations_with_nearby_bmtc_stop": stations_with_nearby,
        "stations_without_nearby_bmtc_stop": len(stations_without_nearby),
        "stations_without_nearby_bmtc_stop_ids": sorted(stations_without_nearby),
        "note": (
            "Proximity within radius does not prove a safe real-world walk; "
            "Journey Builder uses these coordinates for bounded transfer edges only."
        ),
    }


def validate_bmrcl_enriched_payload(payload: Dict[str, Any]) -> List[str]:
    """Extra validation for BMRCL coordinate enrichment (explicit failures)."""
    errors: List[str] = []
    stations = payload.get("stations") or []
    seen_ids = set()
    for raw in stations:
        sid = str(raw.get("id"))
        if sid in seen_ids:
            errors.append(f"DUPLICATE_STATION_ID ({sid})")
        seen_ids.add(sid)
        lat, lon = raw.get("latitude"), raw.get("longitude")
        meta = raw.get("source_metadata") or {}
        status = meta.get("coordinate_match_status")
        if status == "invalid_coordinate" or (
            lat is not None and lon is not None and validate_coordinate_pair(lat, lon)
        ):
            detail = meta.get("coordinate_match_detail") or ",".join(
                validate_coordinate_pair(
                    float(lat) if lat is not None else None,
                    float(lon) if lon is not None else None,
                )
            )
            errors.append(f"STATION_INVALID_ENRICHED_COORDINATES ({sid}: {detail})")
        if lat is not None and lon is not None:
            cp = meta.get("coordinate_provenance") or {}
            if cp.get("source_type") != SourceType.COMMUNITY_UNOFFICIAL.value:
                errors.append(f"STATION_COORD_PROVENANCE_NOT_COMMUNITY ({sid})")
            if meta.get("coordinate_authority") == "OFFICIAL":
                errors.append(f"STATION_COORD_CLAIMED_OFFICIAL ({sid})")
            prov = raw.get("provenance") or {}
            if prov.get("source_type") == SourceType.COMMUNITY_UNOFFICIAL.value:
                errors.append(f"STATION_TOPOLOGY_PROVENANCE_OVERWRITTEN ({sid})")
    return errors
