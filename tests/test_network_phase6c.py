"""
Phase 6C — BMRCL geographic enrichment from community GTFS.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmrcl import build_bmrcl_sync_pipeline
from src.network.ingest.bmrcl_coords import (
    enrich_stations_with_gtfs_coordinates,
    match_station_coordinate,
    normalize_station_name,
    validate_coordinate_pair,
    validate_bmrcl_enriched_payload,
    load_gtfs_station_coordinates,
    GtfsStationCoord,
)
from src.network.models import SourceType
from src.network.sync.validation import validate_network_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
BMRCL_SEED = (
    REPO_ROOT / "data" / "mobility_network" / "bmrcl" / "seed" / "bmrcl_network_seed.json"
)
FIXTURE_GTFS = Path(__file__).parent / "fixtures" / "bmrcl_gtfs_sample"
ALIAS_PATH = (
    REPO_ROOT
    / "data"
    / "mobility_network"
    / "bmrcl"
    / "enrichment"
    / "station_id_aliases.json"
)


class TestCoordinateValidation:
    def test_valid_coordinates(self):
        assert validate_coordinate_pair(12.97, 77.59) == []

    def test_missing_both_ok(self):
        assert validate_coordinate_pair(None, None) == []

    def test_partial_coordinates(self):
        assert "PARTIAL_COORDINATES" in validate_coordinate_pair(12.97, None)
        assert "PARTIAL_COORDINATES" in validate_coordinate_pair(None, 77.59)

    def test_invalid_latitude(self):
        assert "GLOBAL_BOUNDS" in validate_coordinate_pair(999.0, 77.6)

    def test_invalid_longitude(self):
        assert "GLOBAL_BOUNDS" in validate_coordinate_pair(12.97, 999.0)

    def test_zero_coordinate(self):
        assert "ZERO_COORDINATE" in validate_coordinate_pair(0.0, 0.0)

    def test_out_of_bengaluru_bounds(self):
        # Delhi-ish
        errs = validate_coordinate_pair(28.61, 77.21)
        assert "OUT_OF_BENGALURU_BOUNDS" in errs


class TestStationMatching:
    def test_exact_id_alias_match(self):
        gtfs = {
            "BYPH": GtfsStationCoord("BYPH", "Baiyappanahalli", 12.99, 77.65)
        }
        by_name = {
            normalize_station_name("Baiyappanahalli"): [gtfs["BYPH"]]
        }
        aliases = {"baiyyappanahalli": "BYPH"}
        m = match_station_coordinate(
            "baiyyappanahalli", "Baiyyappanahalli", gtfs, by_name, aliases
        )
        assert m.status == "matched"
        assert m.method == "alias_id"
        assert m.gtfs_stop_id == "BYPH"

    def test_exact_normalized_name_match(self):
        hit = GtfsStationCoord("IDN", "Indiranagar", 12.978, 77.638)
        gtfs = {"IDN": hit}
        by_name = {normalize_station_name("Indiranagar"): [hit]}
        m = match_station_coordinate("indiranagar", "Indiranagar", gtfs, by_name, {})
        assert m.status == "matched"
        assert m.method == "exact_normalized_name"

    def test_unmatched_station(self):
        m = match_station_coordinate(
            "unknown_station", "Completely Unknown Metro", {}, {}, {}
        )
        assert m.status == "unmatched"
        assert m.latitude is None

    def test_ambiguous_station(self):
        a = GtfsStationCoord("A1", "Dup Name", 12.9, 77.5)
        b = GtfsStationCoord("A2", "Dup Name", 12.91, 77.51)
        key = normalize_station_name("Dup Name")
        m = match_station_coordinate(
            "dup", "Dup Name", {"A1": a, "A2": b}, {key: [a, b]}, {}
        )
        assert m.status == "ambiguous"
        assert m.latitude is None


class TestEnrichmentPipeline:
    def test_fixture_enriches_and_keeps_topology_provenance(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_bmrcl_sync_pipeline(
            repo, BMRCL_SEED, gtfs_path=FIXTURE_GTFS, alias_path=ALIAS_PATH
        ).run(version="enriched")
        assert result.success and result.published
        active = repo.get_active_snapshot("bmrcl")
        assert active is not None
        stations = {s["id"]: s for s in active.payload["stations"]}

        # Topology provenance remains official
        majestic = stations["nadaprabhu_kempegowda"]
        assert majestic["provenance"]["source_type"] == SourceType.OFFICIAL_OPEN_DATA.value
        assert majestic["latitude"] is not None
        assert majestic["longitude"] is not None
        cp = majestic["source_metadata"]["coordinate_provenance"]
        assert cp["source_type"] == SourceType.COMMUNITY_UNOFFICIAL.value
        assert cp["source_name"] == "Vonter BMRCL GTFS"
        assert "OpenStreetMap" in cp["coordinate_source"]
        assert majestic["source_metadata"]["coordinate_authority"] == "COMMUNITY_UNOFFICIAL"
        assert majestic["source_metadata"]["authority"] == "OFFICIAL"

        # Alias spelling match
        assert stations["baiyyappanahalli"]["latitude"] is not None
        # Unmatched in fixture remains null (e.g. kalena_agrahara not in fixture)
        assert stations["kalena_agrahara"]["latitude"] is None

        meta = active.payload["dataset_meta"]
        assert meta["authority"] == "OFFICIAL"
        assert meta["coordinate_enrichment"]["enabled"] is True
        assert (
            meta["coordinate_enrichment"]["source_type"]
            == SourceType.COMMUNITY_UNOFFICIAL.value
        )
        assert meta["coordinate_quality"]["stations_with_coordinates"] >= 1

    def test_without_gtfs_coordinates_remain_null(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        assert build_bmrcl_sync_pipeline(repo, BMRCL_SEED).run(version="seed").success
        stations = repo.get_active_snapshot("bmrcl").payload["stations"]
        assert all(s.get("latitude") is None for s in stations)

    def test_failed_enrichment_preserves_active(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        good = build_bmrcl_sync_pipeline(
            repo, BMRCL_SEED, gtfs_path=FIXTURE_GTFS, alias_path=ALIAS_PATH
        ).run(version="good")
        assert good.success
        before = repo.get_active_snapshot("bmrcl")
        assert before is not None and before.version == "good"

        # Poison: Attiguppe at (0,0) so exact name match yields invalid coords.
        bad_gtfs = tmp_path / "bad_gtfs"
        bad_gtfs.mkdir()
        (bad_gtfs / "stops.txt").write_text(
            "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
            "AGPP,Attiguppe,0,0,1\n",
            encoding="utf-8",
        )
        (bad_gtfs / "feed_info.txt").write_text(
            "feed_publisher_name,feed_version\nVonter,bad\n", encoding="utf-8"
        )
        bad = build_bmrcl_sync_pipeline(
            repo, BMRCL_SEED, gtfs_path=bad_gtfs, alias_path=ALIAS_PATH
        ).run(version="bad")
        assert not bad.success
        assert not bad.published
        after = repo.get_active_snapshot("bmrcl")
        assert after is not None and after.version == "good"
        assert after.checksum == before.checksum
        assert (tmp_path / "bmrcl" / "failed" / "bad.json").exists()

    def test_validate_enriched_rejects_official_coord_claim(self):
        payload = {
            "stations": [
                {
                    "id": "x",
                    "name": "X",
                    "provider": "BMRCL",
                    "latitude": 12.97,
                    "longitude": 77.59,
                    "provenance": {
                        "source": "bmrcl_official_web_normalized",
                        "source_type": "official_open_data",
                        "retrieved_at": "2024-01-01T00:00:00+00:00",
                    },
                    "source_metadata": {
                        "coordinate_authority": "OFFICIAL",
                        "coordinate_provenance": {
                            "source_type": "community_unofficial",
                        },
                    },
                }
            ]
        }
        errs = validate_bmrcl_enriched_payload(payload)
        assert any("STATION_COORD_CLAIMED_OFFICIAL" in e for e in errs)


class TestGeographicConnectivityFixture:
    def test_proximity_within_and_outside_radius(self):
        from src.network.ingest.bmrcl_coords import geographic_proximity_bmrcl_bmtc

        stations = [
            {
                "id": "metro_a",
                "latitude": 12.9757,
                "longitude": 77.5729,
            }
        ]
        stops_near = [
            {"id": "bus_near", "latitude": 12.9760, "longitude": 77.5730},
            {"id": "bus_far", "latitude": 12.8452, "longitude": 77.6602},
        ]
        report = geographic_proximity_bmrcl_bmtc(stations, stops_near, radius_m=800)
        assert report["relationship"] == "geographic_proximity"
        assert report["stations_with_nearby_bmtc_stop"] == 1
        assert report["stations_without_nearby_bmtc_stop"] == 0
        assert report["nearby_bmtc_stop_links"] == 1

        only_far = geographic_proximity_bmrcl_bmtc(
            stations, [stops_near[1]], radius_m=800
        )
        assert only_far["stations_with_nearby_bmtc_stop"] == 0
        assert only_far["stations_without_nearby_bmtc_stop"] == 1


class TestEntrancesIgnored:
    def test_location_type_entrance_not_loaded_as_station(self):
        coords = load_gtfs_station_coordinates(FIXTURE_GTFS)
        assert "ONLYENT" not in coords
        assert "KGWA" in coords
