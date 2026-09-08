"""
BMTC community GTFS ingest → Phase 5A normalized payload.

Provenance is always COMMUNITY / UNOFFICIAL (Vonter / MobilityDatabase mdb-2595).
Never labeled as BMTC official GTFS.

Compact mode (full community feed):
  Omits bulk ``shapes``, ``stop_times``, and raw GTFS fare tables from the
  published snapshot after deriving route stop sequences and recording counts
  in ``dataset_meta["statistics"]``. This is a size/normalization choice for
  repository practicality — not fabrication and not repair of invalid rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.network.ingest import (
    blank_to_none,
    community_bmtc_provenance,
    read_gtfs_table,
    utc_now,
)
from src.network.models import (
    MobilityMode,
    MobilityRoute,
    MobilityStop,
    MobilityStopTime,
    MobilityTrip,
    SourceType,
    StopType,
)
from src.network.sync import (
    DataSource,
    Fetcher,
    LocalDictDataSource,
    Normalizer,
    Parser,
    SyncPipeline,
)
from src.network.file_repository import FileStaticMobilityRepository


GTFS_ROUTE_TYPE_BUS = {"3", "11", "700", "701", "702", "703", "704", "705"}

# Files inspected for Phase 6A archive inventory (presence ≠ required for publish).
GTFS_INVENTORY_FILES = (
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "shapes.txt",
    "fare_attributes.txt",
    "fare_rules.txt",
    "feed_info.txt",
    "attributions.txt",
    "translations.txt",
)


def list_gtfs_files_present(gtfs_path: Path | str) -> Dict[str, bool]:
    """Report which known GTFS filenames exist in a directory or zip."""
    root = Path(gtfs_path)
    present = {name: False for name in GTFS_INVENTORY_FILES}
    extra: List[str] = []

    if root.is_file() and root.suffix.lower() == ".zip":
        import zipfile

        with zipfile.ZipFile(root) as zf:
            names = {n.split("/")[-1] for n in zf.namelist() if not n.endswith("/")}
        for name in GTFS_INVENTORY_FILES:
            present[name] = name in names
        extra = sorted(n for n in names if n.endswith(".txt") and n not in present)
    else:
        found = {p.name for p in root.rglob("*.txt")}
        for name in GTFS_INVENTORY_FILES:
            present[name] = name in found
        extra = sorted(n for n in found if n not in present)

    out = dict(present)
    out["_extra_txt"] = extra  # type: ignore[assignment]
    return out


class BmtcGtfsFetcher(Fetcher):
    """Load GTFS from a local directory or zip. Does not invent files."""

    def __init__(self, gtfs_path: Path | str):
        self.gtfs_path = Path(gtfs_path)

    def fetch(self) -> Path:
        if not self.gtfs_path.exists():
            raise FileNotFoundError(
                f"BMTC GTFS path not found: {self.gtfs_path}. "
                "Fetch the community feed from "
                "https://github.com/Vonter/bmtc-gtfs "
                "(MobilityDatabase mdb-2595) and point this fetcher at the "
                "extracted folder or zip. Do not commit huge archives to git."
            )
        return self.gtfs_path


class BmtcGtfsParser(Parser):
    """
    Parse GTFS tables into dicts of rows.

    ``load_shapes`` / ``load_fare_tables`` default True (fixture / full fidelity).
    Set False for compact community-feed ingest to avoid multi-GB RAM use.
    """

    def __init__(
        self,
        *,
        load_shapes: bool = True,
        load_fare_tables: bool = True,
    ):
        self.load_shapes = load_shapes
        self.load_fare_tables = load_fare_tables

    def parse(self, raw: Any) -> Dict[str, List[Dict[str, str]]]:
        root = Path(raw) if not isinstance(raw, Path) else raw
        tables: Dict[str, List[Dict[str, str]]] = {
            "agency": read_gtfs_table(root, "agency.txt"),
            "stops": read_gtfs_table(root, "stops.txt"),
            "routes": read_gtfs_table(root, "routes.txt"),
            "trips": read_gtfs_table(root, "trips.txt"),
            "stop_times": read_gtfs_table(root, "stop_times.txt"),
            "calendar": read_gtfs_table(root, "calendar.txt"),
            "calendar_dates": read_gtfs_table(root, "calendar_dates.txt"),
            "shapes": read_gtfs_table(root, "shapes.txt") if self.load_shapes else [],
            "feed_info": read_gtfs_table(root, "feed_info.txt"),
            "fare_attributes": (
                read_gtfs_table(root, "fare_attributes.txt")
                if self.load_fare_tables
                else []
            ),
            "fare_rules": (
                read_gtfs_table(root, "fare_rules.txt")
                if self.load_fare_tables
                else []
            ),
        }
        tables["_parse_options"] = [  # type: ignore[assignment]
            {
                "load_shapes": str(self.load_shapes),
                "load_fare_tables": str(self.load_fare_tables),
                "gtfs_root": str(root),
            }
        ]
        return tables


class BmtcGtfsNormalizer(Normalizer):
    def __init__(
        self,
        *,
        retrieved_at: Optional[datetime] = None,
        compact: bool = False,
    ):
        self.retrieved_at = retrieved_at or utc_now()
        self.compact = compact

    def normalize(self, parsed: Any) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            raise TypeError("BmtcGtfsNormalizer expects parsed GTFS tables dict")

        feed_info = (parsed.get("feed_info") or [None])[0] or {}
        feed_start = blank_to_none(feed_info.get("feed_start_date"))
        feed_end = blank_to_none(feed_info.get("feed_end_date"))
        version = blank_to_none(feed_info.get("feed_version")) or "community-gtfs"
        prov = community_bmtc_provenance(
            retrieved_at=self.retrieved_at,
            version=version,
            feed_start=feed_start,
            feed_end=feed_end,
        )

        stops: List[dict] = []
        stop_ids_kept: Set[str] = set()
        skips_incomplete_stops = 0
        for row in parsed.get("stops") or []:
            stop_id = blank_to_none(row.get("stop_id"))
            lat = blank_to_none(row.get("stop_lat"))
            lon = blank_to_none(row.get("stop_lon"))
            if not stop_id or lat is None or lon is None:
                # Skip incomplete stop rows rather than fabricating coordinates.
                skips_incomplete_stops += 1
                continue
            stops.append(
                MobilityStop(
                    id=stop_id,
                    name=blank_to_none(row.get("stop_name")) or stop_id,
                    latitude=float(lat),
                    longitude=float(lon),
                    provider="BMTC",
                    network="bmtc",
                    stop_type=StopType.BUS_STOP,
                    provenance=prov,
                    accessibility={},
                    source_metadata={
                        "gtfs_stop_code": blank_to_none(row.get("stop_code")),
                        "community_feed": True,
                        "authority": "COMMUNITY_UNOFFICIAL",
                    },
                ).to_dict()
            )
            stop_ids_kept.add(stop_id)

        # Build stop sequences from stop_times when present.
        trip_stop_seq: Dict[str, List[tuple]] = defaultdict(list)
        stop_times_out: List[dict] = []
        stop_times_rows = 0
        trips_with_schedule: Set[str] = set()
        for row in parsed.get("stop_times") or []:
            trip_id = blank_to_none(row.get("trip_id"))
            stop_id = blank_to_none(row.get("stop_id"))
            seq = blank_to_none(row.get("stop_sequence"))
            if not trip_id or not stop_id or seq is None:
                continue
            stop_times_rows += 1
            arrival = blank_to_none(row.get("arrival_time"))
            departure = blank_to_none(row.get("departure_time"))
            if arrival or departure:
                trips_with_schedule.add(trip_id)
            # Do NOT replace missing times with 00:00:00.
            if not self.compact:
                st = MobilityStopTime(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    stop_sequence=int(seq),
                    provenance=prov,
                    arrival_time=arrival,
                    departure_time=departure,
                    source_metadata={"community_feed": True},
                )
                stop_times_out.append(st.to_dict())
            trip_stop_seq[trip_id].append((int(seq), stop_id))

        route_stop_ids: Dict[str, List[str]] = {}
        trips_by_route: Dict[str, List[str]] = defaultdict(list)
        trips_out: List[dict] = []
        trip_shape_ids: Dict[str, Optional[str]] = {}
        for row in parsed.get("trips") or []:
            trip_id = blank_to_none(row.get("trip_id"))
            route_id = blank_to_none(row.get("route_id"))
            service_id = blank_to_none(row.get("service_id"))
            if not trip_id or not route_id or not service_id:
                continue
            shape_id = blank_to_none(row.get("shape_id"))
            trip_shape_ids[trip_id] = shape_id
            if not self.compact:
                trips_out.append(
                    MobilityTrip(
                        id=trip_id,
                        route_id=route_id,
                        service_id=service_id,
                        provenance=prov,
                        headsign=blank_to_none(row.get("trip_headsign")),
                        direction_id=blank_to_none(row.get("direction_id")),
                        shape_id=shape_id,
                        source_metadata={"community_feed": True},
                    ).to_dict()
                )
            trips_by_route[route_id].append(trip_id)
            ordered = [
                sid
                for _, sid in sorted(trip_stop_seq.get(trip_id, []), key=lambda x: x[0])
            ]
            # Prefer the longest observed stop sequence for the route.
            if ordered and (
                route_id not in route_stop_ids
                or len(ordered) > len(route_stop_ids[route_id])
            ):
                route_stop_ids[route_id] = ordered

        routes_out: List[dict] = []
        routes_with_shapes = 0
        for row in parsed.get("routes") or []:
            route_id = blank_to_none(row.get("route_id"))
            if not route_id:
                continue
            route_type = blank_to_none(row.get("route_type")) or ""
            has_shape = any(
                trip_shape_ids.get(tid) for tid in trips_by_route.get(route_id) or []
            )
            if has_shape:
                routes_with_shapes += 1
            # Keep all routes; annotate type. Do not assume operational status.
            routes_out.append(
                MobilityRoute(
                    id=route_id,
                    name=blank_to_none(row.get("route_long_name"))
                    or blank_to_none(row.get("route_short_name"))
                    or route_id,
                    provider="BMTC",
                    network="bmtc",
                    mode=MobilityMode.BUS,
                    provenance=prov,
                    short_name=blank_to_none(row.get("route_short_name")),
                    stop_ids=tuple(route_stop_ids.get(route_id) or ()),
                    geometry_ref=None,
                    service_metadata={
                        "gtfs_route_type": route_type,
                        "gtfs_route_type_is_bus_like": route_type in GTFS_ROUTE_TYPE_BUS
                        or route_type == "3",
                        "operational_status": "unknown_from_community_feed",
                        "trip_count": len(trips_by_route.get(route_id) or []),
                        "has_shape_ref": has_shape,
                    },
                    source_metadata={
                        "community_feed": True,
                        "authority": "COMMUNITY_UNOFFICIAL",
                        "mobilitydatabase": "mdb-2595",
                        "producer": "https://github.com/Vonter/bmtc-gtfs",
                    },
                ).to_dict()
            )

        shapes_out: List[dict] = []
        shape_point_count = 0
        shape_ids: Set[str] = set()
        for row in parsed.get("shapes") or []:
            shape_id = blank_to_none(row.get("shape_id"))
            lat = blank_to_none(row.get("shape_pt_lat"))
            lon = blank_to_none(row.get("shape_pt_lon"))
            seq = blank_to_none(row.get("shape_pt_sequence"))
            if not shape_id or lat is None or lon is None or seq is None:
                continue
            shape_point_count += 1
            shape_ids.add(shape_id)
            if not self.compact:
                shapes_out.append(
                    {
                        "shape_id": shape_id,
                        "lat": float(lat),
                        "lon": float(lon),
                        "sequence": int(seq),
                        "provenance": prov.to_dict(),
                    }
                )

        # If shapes were omitted at parse time, recover counts from trip shape refs.
        parse_opts = (parsed.get("_parse_options") or [{}])[0]
        shapes_loaded = str(parse_opts.get("load_shapes", "True")).lower() == "true"
        if not shapes_loaded:
            shape_ids = {s for s in trip_shape_ids.values() if s}
            shape_point_count = -1  # unknown without shapes.txt load

        calendars = {
            "calendar": parsed.get("calendar") or [],
            "calendar_dates": parsed.get("calendar_dates") or [],
        }

        fare_related = {
            "fare_attributes": parsed.get("fare_attributes") or [],
            "fare_rules_gtfs": parsed.get("fare_rules") or [],
        }
        if self.compact:
            fare_related = {
                "fare_attributes": [],
                "fare_rules_gtfs": [],
                "omitted_for_compact_snapshot": True,
                "fare_attributes_row_count": len(parsed.get("fare_attributes") or []),
                "fare_rules_row_count": len(parsed.get("fare_rules") or []),
            }

        lats = [s["latitude"] for s in stops]
        lons = [s["longitude"] for s in stops]
        bbox = None
        if lats and lons:
            bbox = {
                "min_lat": min(lats),
                "max_lat": max(lats),
                "min_lon": min(lons),
                "max_lon": max(lons),
            }

        cal_starts = []
        cal_ends = []
        for row in calendars["calendar"]:
            s = blank_to_none(row.get("start_date"))
            e = blank_to_none(row.get("end_date"))
            if s:
                cal_starts.append(s)
            if e:
                cal_ends.append(e)

        statistics = {
            "total_stops": len(stops),
            "stops_with_valid_coordinates": len(stops),
            "stops_skipped_incomplete": skips_incomplete_stops,
            "total_routes": len(routes_out),
            "total_trips": sum(len(v) for v in trips_by_route.values()),
            "total_stop_times": stop_times_rows,
            "shape_points": shape_point_count,
            "shape_ids": len(shape_ids),
            "routes_with_shapes": routes_with_shapes,
            "trips_with_usable_schedules": len(trips_with_schedule),
            "service_calendar_rows": len(calendars["calendar"]),
            "calendar_dates_rows": len(calendars["calendar_dates"]),
            "earliest_service_date": min(cal_starts) if cal_starts else feed_start,
            "latest_service_date": max(cal_ends) if cal_ends else feed_end,
            "bounding_box": bbox,
            "compact_snapshot": self.compact,
            "shapes_loaded_in_parse": shapes_loaded,
            "normalization_notes": (
                [
                    "compact=True: stop_times/shapes/trips/gtfs fare tables omitted "
                    "from published payload after deriving route.stop_ids and stats; "
                    "authority remains COMMUNITY_UNOFFICIAL."
                ]
                if self.compact
                else []
            ),
        }

        return {
            "stops": stops,
            "stations": [],
            "routes": routes_out,
            "fare_rules": [],  # GTFS fare tables kept raw below; not assumed complete
            "trips": trips_out,
            "stop_times": stop_times_out,
            "shapes": shapes_out,
            "calendars": calendars,
            "agencies": parsed.get("agency") or [],
            "gtfs_fare_tables": fare_related,
            "dataset_meta": {
                "authority": "COMMUNITY_UNOFFICIAL",
                "provider_label": "BMTC schedule data — community GTFS",
                "mobilitydatabase_id": "mdb-2595",
                "producer_url": "https://github.com/Vonter/bmtc-gtfs",
                "listing_url": "https://mobilitydatabase.org/feeds/gtfs/mdb-2595",
                "feed_start_date": feed_start,
                "feed_end_date": feed_end,
                "feed_version": version,
                "provenance": prov.to_dict(),
                "statistics": statistics,
            },
        }


def build_bmtc_sync_pipeline(
    gtfs_path: Path | str,
    repository: FileStaticMobilityRepository,
    *,
    compact: bool = False,
) -> SyncPipeline:
    """
    Build the Phase 5B BMTC sync pipeline.

    For the full community archive, pass ``compact=True`` so the published
    snapshot retains topology (stops + route sequences) without multi-GB
    shapes/stop_times arrays. Fixtures should keep the default ``compact=False``.
    """
    return SyncPipeline(
        source=LocalDictDataSource(
            name="bmtc",
            provider_name="BMTC",
            source_label="bmtc_gtfs_community_vonter",
        ),
        fetcher=BmtcGtfsFetcher(gtfs_path),
        parser=BmtcGtfsParser(
            load_shapes=not compact,
            load_fare_tables=not compact,
        ),
        normalizer=BmtcGtfsNormalizer(compact=compact),
        repository=repository,
        source_type=SourceType.COMMUNITY_UNOFFICIAL,
        source_url="https://github.com/Vonter/bmtc-gtfs",
    )
