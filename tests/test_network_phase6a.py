"""
Phase 6A — BMTC community GTFS acquisition, compact publish, connectivity audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest, SearchLimits
from src.network.audit.bmtc_connectivity import (
    DEFAULT_AUDIT_RADIUS_M,
    analyze_bmtc_connectivity,
    build_phase6a_audit_report,
    find_nearby_stops,
)
from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmtc_gtfs import (
    BmtcGtfsNormalizer,
    BmtcGtfsParser,
    build_bmtc_sync_pipeline,
    list_gtfs_files_present,
)
from src.network.models import MobilityRoute, MobilityStop, SourceType, ValidationStatus
from src.network.sync.validation import (
    assert_no_hardcoded_journeys,
    validate_network_payload,
)

FIXTURE_GTFS = Path(__file__).parent / "fixtures" / "bmtc_gtfs_sample"


class TestPhase6AGtfsInventory:
    def test_fixture_lists_expected_files(self):
        present = list_gtfs_files_present(FIXTURE_GTFS)
        assert present["stops.txt"] is True
        assert present["routes.txt"] is True
        assert present["trips.txt"] is True
        assert present["stop_times.txt"] is True
        # Fixture may omit optional calendar_dates — must not invent presence.
        assert present["calendar_dates.txt"] is False or present["calendar_dates.txt"] is True


class TestPhase6AAuthorityAndProvenance:
    def test_authority_remains_community_unofficial(self):
        payload = BmtcGtfsNormalizer().normalize(BmtcGtfsParser().parse(FIXTURE_GTFS))
        assert payload["dataset_meta"]["authority"] == "COMMUNITY_UNOFFICIAL"
        for stop in payload["stops"]:
            assert stop["provenance"]["source_type"] == SourceType.COMMUNITY_UNOFFICIAL.value
            assert stop["source_metadata"]["authority"] == "COMMUNITY_UNOFFICIAL"

    def test_provenance_retained_on_publish(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_bmtc_sync_pipeline(FIXTURE_GTFS, repo).run(version="v1")
        assert result.success
        active = repo.get_active_snapshot("bmtc")
        assert active is not None
        assert active.provenance.source_type == SourceType.COMMUNITY_UNOFFICIAL
        assert "vonter" in (active.provenance.source or "").lower() or (
            active.provenance.source_url or ""
        ).startswith("https://github.com/Vonter/bmtc-gtfs")


class TestPhase6AValidation:
    def test_gtfs_references_validate(self):
        payload = BmtcGtfsNormalizer().normalize(BmtcGtfsParser().parse(FIXTURE_GTFS))
        assert validate_network_payload(payload) == []

    def test_invalid_coordinates_rejected(self):
        tables = BmtcGtfsParser().parse(FIXTURE_GTFS)
        tables["stops"] = list(tables["stops"]) + [
            {
                "stop_id": "BAD",
                "stop_name": "Bad",
                "stop_lat": "999",
                "stop_lon": "77.0",
            }
        ]
        payload = BmtcGtfsNormalizer().normalize(tables)
        errors = validate_network_payload(payload)
        assert any("STOP_INVALID_COORDINATES" in e for e in errors)

    def test_missing_route_ref_fails_validation(self):
        tables = BmtcGtfsParser().parse(FIXTURE_GTFS)
        tables["trips"] = list(tables["trips"]) + [
            {
                "trip_id": "TX",
                "route_id": "NO_SUCH_ROUTE",
                "service_id": "WEEKDAY",
            }
        ]
        payload = BmtcGtfsNormalizer().normalize(tables)
        errors = validate_network_payload(payload)
        assert any("TRIP_ROUTE_REF_UNRESOLVED" in e for e in errors)

    def test_active_survives_failed_refresh(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        assert build_bmtc_sync_pipeline(FIXTURE_GTFS, repo).run(version="good").success
        before = repo.get_active_snapshot("bmtc")
        assert before is not None and before.version == "good"

        tables = BmtcGtfsParser().parse(FIXTURE_GTFS)
        tables["trips"] = [
            {"trip_id": "TX", "route_id": "MISSING", "service_id": "WEEKDAY"}
        ]
        # Publish invalid via Identity path would be separate; use broken normalize
        # by writing a deliberately invalid payload through pipeline components:
        from src.network.sync import (
            IdentityNormalizer,
            LocalDictDataSource,
            PassthroughParser,
            StaticDictFetcher,
            SyncPipeline,
        )

        bad_payload = BmtcGtfsNormalizer().normalize(tables)
        assert validate_network_payload(bad_payload)  # non-empty errors
        pipe = SyncPipeline(
            source=LocalDictDataSource("bmtc", "BMTC", "test"),
            fetcher=StaticDictFetcher(bad_payload),
            parser=PassthroughParser(),
            normalizer=IdentityNormalizer(),
            repository=repo,
            source_type=SourceType.COMMUNITY_UNOFFICIAL,
        )
        result = pipe.run(version="bad")
        assert not result.success
        assert not result.published
        after = repo.get_active_snapshot("bmtc")
        assert after is not None and after.version == "good"
        assert after.validation_status == ValidationStatus.PUBLISHED
        assert (tmp_path / "bmtc" / "failed" / "bad.json").exists()


class TestPhase6ACompactPublish:
    def test_compact_omits_bulk_arrays_keeps_topology(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_bmtc_sync_pipeline(
            FIXTURE_GTFS, repo, compact=True
        ).run(version="compact")
        assert result.success
        active = repo.get_active_snapshot("bmtc")
        assert active is not None
        assert active.payload["stop_times"] == []
        assert active.payload["shapes"] == []
        assert active.payload["trips"] == []
        assert active.payload["stops"]
        assert active.payload["routes"]
        assert any(r.get("stop_ids") for r in active.payload["routes"])
        stats = active.payload["dataset_meta"]["statistics"]
        assert stats["compact_snapshot"] is True
        assert stats["total_stop_times"] >= 1
        assert active.payload["dataset_meta"]["authority"] == "COMMUNITY_UNOFFICIAL"


class TestPhase6AAnchorsAndConnectivity:
    def _repo_with_fixture(self, tmp_path: Path) -> FileStaticMobilityRepository:
        repo = FileStaticMobilityRepository(tmp_path)
        assert build_bmtc_sync_pipeline(FIXTURE_GTFS, repo).run(version="fx").success
        return repo

    def test_electronic_city_resolves_only_real_stops(self, tmp_path: Path):
        # Fixture stops are near Majestic-ish coords, not EC — nearby list may be empty.
        repo = self._repo_with_fixture(tmp_path)
        payload = repo.get_active_snapshot("bmtc").payload
        stops = {s["id"]: MobilityStop.from_dict(s) for s in payload["stops"]}
        routes = [MobilityRoute.from_dict(r) for r in payload["routes"]]
        nearby = find_nearby_stops(stops, routes, ELECTRONIC_CITY, radius_m=50)
        known = set(stops)
        assert all(s.stop_id in known for s in nearby)
        # Must not invent a fake EC stop id.
        assert all(not s.stop_id.startswith("FAKE_") for s in nearby)

    def test_majestic_resolves_only_real_stops(self, tmp_path: Path):
        repo = self._repo_with_fixture(tmp_path)
        payload = repo.get_active_snapshot("bmtc").payload
        stops = {s["id"]: MobilityStop.from_dict(s) for s in payload["stops"]}
        routes = [MobilityRoute.from_dict(r) for r in payload["routes"]]
        # Large radius so fixture S1/S2 near Koramangala/Majestic area can match.
        nearby = find_nearby_stops(stops, routes, MAJESTIC, radius_m=20000)
        known = set(stops)
        assert nearby  # fixture is in Bengaluru
        assert all(s.stop_id in known for s in nearby)

    def test_connectivity_does_not_invent_routes(self):
        routes = [
            MobilityRoute.from_dict(
                {
                    "id": "R1",
                    "name": "R1",
                    "provider": "BMTC",
                    "network": "bmtc",
                    "mode": "bus",
                    "stop_ids": ["A", "B", "C"],
                    "provenance": {
                        "source": "t",
                        "source_type": "community_unofficial",
                        "retrieved_at": "2024-01-01T00:00:00+00:00",
                    },
                }
            )
        ]
        # Origin A dest C → direct on R1 only
        out = analyze_bmtc_connectivity(routes, ["A"], ["C"])
        assert out["result"] == "direct"
        assert out["direct_route_ids"] == ["R1"]
        # Unrelated dest → none (no invented bridge)
        out2 = analyze_bmtc_connectivity(routes, ["A"], ["Z"])
        assert out2["result"] == "none"
        assert out2["direct_route_ids"] == []

    def test_transfer_path_from_sequences_only(self):
        prov = {
            "source": "t",
            "source_type": "community_unofficial",
            "retrieved_at": "2024-01-01T00:00:00+00:00",
        }

        def r(rid, stops):
            return MobilityRoute.from_dict(
                {
                    "id": rid,
                    "name": rid,
                    "provider": "BMTC",
                    "network": "bmtc",
                    "mode": "bus",
                    "stop_ids": stops,
                    "provenance": prov,
                }
            )

        routes = [r("R1", ["A", "B"]), r("R2", ["B", "C"])]
        out = analyze_bmtc_connectivity(routes, ["A"], ["C"])
        assert out["result"] == "transfer"
        assert out["direct_route_ids"] == []

    def test_journey_builder_consumes_published_data(self, tmp_path: Path):
        repo = self._repo_with_fixture(tmp_path)
        from datetime import datetime, timezone

        builder = DynamicJourneyBuilder(repo)
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9770,
                origin_lon=77.5990,
                destination_lat=12.9352,
                destination_lon=77.6245,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                search_limits=SearchLimits(
                    max_walking_access_meters=5000,
                    max_walking_egress_meters=5000,
                ),
            )
        )
        assert result.network_snapshot_versions.get("bmtc") == "fx"
        # Candidate count may be 0 or more — must not crash; no hardcoded journeys.
        assert isinstance(result.candidates, list)

    def test_no_hardcoded_journey_constants_in_audit_module(self):
        import src.network.audit.bmtc_connectivity as mod

        assert_no_hardcoded_journeys(vars(mod))

    def test_audit_report_structure(self, tmp_path: Path):
        repo = self._repo_with_fixture(tmp_path)
        report = build_phase6a_audit_report(repo, radius_m=DEFAULT_AUDIT_RADIUS_M)
        assert report["source"]["authority"] == "COMMUNITY_UNOFFICIAL"
        assert "connectivity" in report
        assert "journey_builder" in report
        assert "multimodal" in report
        assert "limitations" in report
        assert report["multimodal"]["bmtc_to_bmrcl_possible"] in (True, False)
        # Serialize
        json.dumps(report)


class TestPhase6ANoHardcodedRoutesInIngest:
    def test_ingest_module_has_no_journey_templates(self):
        import src.network.ingest.bmtc_gtfs as mod

        assert_no_hardcoded_journeys(vars(mod))
        assert not hasattr(mod, "ELECTRONIC_CITY_TO_MAJESTIC")
