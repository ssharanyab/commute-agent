"""
BMRCL metro static importer.

Uses a versioned normalized seed derived from official BMRCL website materials
for topology. Optional Phase 6C enrichment applies COMMUNITY_UNOFFICIAL
coordinates from Vonter/bmrcl-gtfs (OSM-derived). Does NOT invent coordinates
or treat community GTFS timetables as authoritative.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest import bmrcl_official_derived_provenance, blank_to_none, utc_now
from src.network.ingest.bmrcl_coords import (
    BMRCL_GTFS_SOURCE_URL,
    coordinate_quality_stats,
    enrich_stations_with_gtfs_coordinates,
    validate_bmrcl_enriched_payload,
)
from src.network.models import (
    MobilityMode,
    MobilityRoute,
    MobilityStation,
    SourceType,
)
from src.network.sync import (
    DefaultNetworkValidator,
    Fetcher,
    LocalDictDataSource,
    Normalizer,
    PassthroughParser,
    SyncPipeline,
    Validator,
)
from src.network.sync.validation import validate_network_payload

# Default seed path (checked into repo — compact, provenance-bearing).
DEFAULT_BMRCL_SEED = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "mobility_network"
    / "bmrcl"
    / "seed"
    / "bmrcl_network_seed.json"
)

DEFAULT_BMRCL_FARE_RULES = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "mobility_network"
    / "bmrcl"
    / "fares"
    / "bmrcl_token_fare_slabs_v20250214.json"
)


class BmrclSeedFetcher(Fetcher):
    def __init__(self, seed_path: Path | str = DEFAULT_BMRCL_SEED):
        self.seed_path = Path(seed_path)

    def fetch(self) -> Dict[str, Any]:
        if not self.seed_path.exists():
            raise FileNotFoundError(
                f"BMRCL seed artifact missing: {self.seed_path}. "
                "Replace with a future official CSV/JSON/GTFS without changing "
                "StaticMobilityDataRepository."
            )
        return json.loads(self.seed_path.read_text(encoding="utf-8"))


class BmrclSeedNormalizer(Normalizer):
    """
    Normalize official-derived topology seed.

    When ``gtfs_path`` is set, enrich station coordinates from the community
    BMRCL GTFS without changing topology provenance.
    """

    def __init__(
        self,
        *,
        retrieved_at: Optional[datetime] = None,
        gtfs_path: Optional[Path | str] = None,
        alias_path: Optional[Path | str] = None,
    ):
        self.retrieved_at = retrieved_at or utc_now()
        self.gtfs_path = Path(gtfs_path) if gtfs_path else None
        self.alias_path = alias_path

    def normalize(self, parsed: Any) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            raise TypeError("BMRCL seed must be a dict")
        version = str(parsed.get("version") or "seed")
        prov = bmrcl_official_derived_provenance(
            retrieved_at=self.retrieved_at, version=version
        )
        stations_out: List[dict] = []
        for raw in parsed.get("stations") or []:
            lat = raw.get("latitude", None)
            lon = raw.get("longitude", None)
            # Refuse fabricated zeros unless explicitly provided as real coords.
            if lat == 0 and lon == 0 and not raw.get("coordinates_verified"):
                lat, lon = None, None
            stations_out.append(
                MobilityStation(
                    id=str(raw["id"]),
                    name=str(raw["name"]),
                    provider="BMRCL",
                    provenance=prov,
                    latitude=float(lat) if lat is not None else None,
                    longitude=float(lon) if lon is not None else None,
                    lines=tuple(raw.get("lines") or ()),
                    line_order={
                        str(k): int(v)
                        for k, v in dict(raw.get("line_order") or {}).items()
                    },
                    interchange_station_ids=tuple(
                        raw.get("interchange_station_ids") or ()
                    ),
                    accessibility=dict(raw.get("accessibility") or {}),
                    source_metadata={
                        "authority": "OFFICIAL",
                        "normalized_from": "bmrcl_official_web",
                        "source_url": prov.source_url,
                        **dict(raw.get("source_metadata") or {}),
                    },
                ).to_dict()
            )

        enrichment_meta: Dict[str, Any] = {}
        if self.gtfs_path is not None:
            if not self.gtfs_path.exists():
                raise FileNotFoundError(
                    f"BMRCL community GTFS path not found: {self.gtfs_path}. "
                    f"Fetch from {BMRCL_GTFS_SOURCE_URL} (gtfs/bmrcl.zip)."
                )
            feed_rows = []
            try:
                from src.network.ingest import read_gtfs_table

                feed_rows = read_gtfs_table(self.gtfs_path, "feed_info.txt")
            except Exception:
                feed_rows = []
            feed_version = None
            if feed_rows:
                feed_version = blank_to_none(feed_rows[0].get("feed_version"))
            kwargs = {
                "retrieved_at": self.retrieved_at,
                "feed_version": feed_version or version,
            }
            if self.alias_path is not None:
                kwargs["alias_path"] = self.alias_path
            stations_out, _report, enrichment_meta = (
                enrich_stations_with_gtfs_coordinates(
                    stations_out, self.gtfs_path, **kwargs
                )
            )

        routes_out: List[dict] = []
        for raw in parsed.get("lines") or []:
            line_id = str(raw["id"])
            with_order = []
            without_order = []
            for st in parsed.get("stations") or []:
                if line_id not in (st.get("lines") or []):
                    continue
                order = dict(st.get("line_order") or {}).get(line_id)
                if order is not None:
                    with_order.append((int(order), str(st["id"])))
                else:
                    without_order.append(str(st["id"]))
            with_order.sort(key=lambda x: x[0])
            stop_ids = tuple(sid for _, sid in with_order) + tuple(without_order)

            routes_out.append(
                MobilityRoute(
                    id=line_id,
                    name=str(raw.get("name") or line_id),
                    provider="BMRCL",
                    network="bmrcl",
                    mode=MobilityMode.METRO,
                    provenance=prov,
                    short_name=raw.get("short_name"),
                    stop_ids=stop_ids,
                    geometry_ref=None,
                    service_metadata={
                        "color": raw.get("color"),
                        "line_kind": "metro",
                        "authority": "OFFICIAL",
                    },
                    source_metadata={
                        "authority": "OFFICIAL",
                        "normalized_from": "bmrcl_official_web",
                    },
                ).to_dict()
            )

        fare_rules = list(parsed.get("fare_rules") or [])
        if not fare_rules and DEFAULT_BMRCL_FARE_RULES.exists():
            fare_doc = json.loads(
                DEFAULT_BMRCL_FARE_RULES.read_text(encoding="utf-8")
            )
            fare_rules = list(fare_doc.get("fare_rules") or [])
        for fr in fare_rules:
            if "provenance" not in fr:
                fr["provenance"] = prov.to_dict()
            fr.setdefault("provider", "BMRCL")
            fr.setdefault("network", "bmrcl")
            fr.setdefault("mode", "metro")

        dataset_meta: Dict[str, Any] = {
            "authority": "OFFICIAL",
            "normalized_derived": True,
            "source_url": prov.source_url,
            "website": "https://english.bmrc.co.in/",
            "provenance": prov.to_dict(),
            "notes": (
                "Topology from official BMRCL website materials. "
                "Coordinates omitted unless community GTFS enrichment is applied; "
                "enriched coordinates are COMMUNITY_UNOFFICIAL (OSM-derived)."
            ),
            "coordinate_quality": coordinate_quality_stats(stations_out),
        }
        if enrichment_meta:
            dataset_meta.update(enrichment_meta)

        return {
            "stops": [],
            "stations": stations_out,
            "routes": routes_out,
            "fare_rules": fare_rules,
            "lines_meta": parsed.get("lines") or [],
            "dataset_meta": dataset_meta,
        }


class BmrclNetworkValidator(Validator):
    """Default network validation plus BMRCL coordinate-enrichment checks."""

    def validate(self, payload: Dict[str, Any]) -> List[str]:
        errors = list(validate_network_payload(payload))
        meta = payload.get("dataset_meta") or {}
        if meta.get("coordinate_enrichment", {}).get("enabled"):
            errors.extend(validate_bmrcl_enriched_payload(payload))
        return errors


def build_bmrcl_sync_pipeline(
    repository: FileStaticMobilityRepository,
    seed_path: Path | str = DEFAULT_BMRCL_SEED,
    *,
    gtfs_path: Optional[Path | str] = None,
    alias_path: Optional[Path | str] = None,
) -> SyncPipeline:
    """
    Build BMRCL sync pipeline.

    Pass ``gtfs_path`` (dir or .zip from Vonter/bmrcl-gtfs) to enable Phase 6C
    geographic enrichment. Without it, coordinates remain omitted (Phase 5B).
    """
    return SyncPipeline(
        source=LocalDictDataSource(
            name="bmrcl",
            provider_name="BMRCL",
            source_label="bmrcl_official_web_normalized",
        ),
        fetcher=BmrclSeedFetcher(seed_path),
        parser=PassthroughParser(),
        normalizer=BmrclSeedNormalizer(
            gtfs_path=gtfs_path,
            alias_path=alias_path,
        ),
        repository=repository,
        validator=BmrclNetworkValidator() if gtfs_path else DefaultNetworkValidator(),
        source_type=SourceType.OFFICIAL_OPEN_DATA,
        source_url="https://english.bmrc.co.in/schematic-route-map/",
    )
