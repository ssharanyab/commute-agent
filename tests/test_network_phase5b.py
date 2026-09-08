"""
Phase 5B — Bengaluru static mobility ingest into Phase 5A contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmtc_gtfs import (
    BmtcGtfsNormalizer,
    BmtcGtfsParser,
    build_bmtc_sync_pipeline,
)
from src.network.ingest.bmrcl import build_bmrcl_sync_pipeline
from src.network.ingest.fares import (
    apply_fare_rules,
    build_auto_fare_rule,
    build_auto_fare_sync_pipeline,
    build_shakti_fare_rule,
    build_shakti_sync_pipeline,
    compute_auto_fare_inr,
)
from src.network.models import (
    MobilityMode,
    MobilityStop,
    SourceType,
    ValidationStatus,
)
from src.network.registry import get_dataset
from src.network.sync import (
    IdentityNormalizer,
    LocalDictDataSource,
    PassthroughParser,
    StaticDictFetcher,
    SyncPipeline,
)
from src.network.sync.validation import validate_network_payload

FIXTURE_GTFS = Path(__file__).parent / "fixtures" / "bmtc_gtfs_sample"
REPO_ROOT = Path(__file__).resolve().parents[1]
BMRCL_SEED = (
    REPO_ROOT / "data" / "mobility_network" / "bmrcl" / "seed" / "bmrcl_network_seed.json"
)
AUTO_SEED = (
    REPO_ROOT
    / "data"
    / "mobility_network"
    / "auto_fares"
    / "seed"
    / "bengaluru_auto_fare.json"
)
SHAKTI_SEED = (
    REPO_ROOT / "data" / "mobility_network" / "shakti" / "seed" / "shakti_fare_policy.json"
)


class TestBmtcCommunityGtfs:
    def test_stops_routes_trips_stop_times_normalize(self):
        tables = BmtcGtfsParser().parse(FIXTURE_GTFS)
        payload = BmtcGtfsNormalizer().normalize(tables)
        assert validate_network_payload(payload) == []

        stops = {s["id"]: MobilityStop.from_dict(s) for s in payload["stops"]}
        assert set(stops) == {"S1", "S2"}  # incomplete S3 skipped
        assert stops["S1"].latitude == pytest.approx(12.9770)
        assert stops["S2"].longitude == pytest.approx(77.6408)

        routes = {r["id"]: r for r in payload["routes"]}
        assert routes["R500"]["short_name"] == "500"
        assert routes["R500"]["mode"] == "bus"
        assert list(routes["R500"]["stop_ids"]) == ["S1", "S2"]
        assert routes["R999"]["service_metadata"]["operational_status"] == (
            "unknown_from_community_feed"
        )

        trips = {t["id"]: t for t in payload["trips"]}
        assert trips["T500A"]["route_id"] == "R500"
        assert trips["T500A"]["service_id"] == "WEEKDAY"

        stop_times = payload["stop_times"]
        assert len(stop_times) == 2
        first, second = stop_times[0], stop_times[1]
        assert first["arrival_time"] == "08:00:00"
        assert second["arrival_time"] is None  # not fabricated
        assert second["departure_time"] == "08:25:00"
        assert "00:00:00" not in (second["arrival_time"] or "")

        assert payload["shapes"]
        assert payload["calendars"]["calendar"]
        meta = payload["dataset_meta"]
        assert meta["authority"] == "COMMUNITY_UNOFFICIAL"
        assert meta["provider_label"] == "BMTC schedule data — community GTFS"
        notes = (payload["routes"][0]["provenance"].get("notes") or "").lower()
        assert "unofficial" in notes
        assert "not bmtc official" in notes

    def test_provenance_is_community_unofficial(self):
        tables = BmtcGtfsParser().parse(FIXTURE_GTFS)
        payload = BmtcGtfsNormalizer().normalize(tables)
        prov = payload["stops"][0]["provenance"]
        assert prov["source_type"] == SourceType.COMMUNITY_UNOFFICIAL.value
        notes = (prov.get("notes") or "").lower()
        assert "community" in notes and "unofficial" in notes
        assert "not bmtc official gtfs" in notes
        assert "mdb-2595" in (payload["dataset_meta"].get("mobilitydatabase_id") or "")

    def test_sync_pipeline_publishes(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_bmtc_sync_pipeline(FIXTURE_GTFS, repo).run(version="bmtc-sample")
        assert result.success and result.published
        active = repo.get_active_snapshot("bmtc")
        assert active is not None
        assert active.provenance.source_type == SourceType.COMMUNITY_UNOFFICIAL
        assert active.checksum


class TestBmrclOfficialSeed:
    def test_stations_lines_interchange_and_provenance(self, tmp_path: Path):
        assert BMRCL_SEED.exists()
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_bmrcl_sync_pipeline(repo, BMRCL_SEED).run(version="bmrcl-seed")
        assert result.success and result.published
        active = repo.get_active_snapshot("bmrcl")
        assert active is not None
        payload = active.payload
        assert validate_network_payload(payload) == []

        stations = {s["id"]: s for s in payload["stations"]}
        assert "nadaprabhu_kempegowda" in stations
        majestic = stations["nadaprabhu_kempegowda"]
        assert set(majestic["lines"]) >= {"purple", "green"}
        assert "nadaprabhu_kempegowda" in majestic["interchange_station_ids"]
        # Coordinates not fabricated
        assert majestic.get("latitude") is None
        assert majestic.get("longitude") is None

        routes = {r["id"]: r for r in payload["routes"]}
        assert routes["purple"]["mode"] == "metro"
        purple_seq = list(routes["purple"]["stop_ids"])
        assert purple_seq[0] == "baiyyappanahalli"
        assert "nadaprabhu_kempegowda" in purple_seq
        green_seq = list(routes["green"]["stop_ids"])
        assert green_seq.index("nagasandra") < green_seq.index("nadaprabhu_kempegowda")
        assert green_seq.index("nadaprabhu_kempegowda") < green_seq.index("silk_institute")

        prov = majestic["provenance"]
        assert prov["source_type"] == SourceType.OFFICIAL_OPEN_DATA.value
        assert "bmrc.co.in" in (prov.get("source_url") or "")
        assert payload["dataset_meta"]["authority"] == "OFFICIAL"
        assert payload["dataset_meta"]["normalized_derived"] is True
        assert active.provenance.source_type == SourceType.OFFICIAL_OPEN_DATA


class TestAutoFare:
    def test_regulated_structure_and_night(self):
        rule = build_auto_fare_rule()
        assert rule.base_fare == 36.0
        structure = rule.rule_structure
        assert structure["minimum"]["fare_inr"] == 36.0
        assert structure["minimum"]["distance_km"] == 2.0
        assert structure["per_km_after_minimum_inr"] == 18.0
        assert structure["night"]["multiplier"] == 1.5
        assert structure["not_live_aggregator"] is True
        assert rule.provenance.source_type == SourceType.GOVERNMENT_REGULATED

        assert compute_auto_fare_inr(rule, distance_km=2.0) == 36.0
        assert compute_auto_fare_inr(rule, distance_km=3.0) == 54.0  # 36 + 18
        night = compute_auto_fare_inr(
            rule, distance_km=2.0, local_time_hhmm="23:00"
        )
        assert night == 54.0  # 36 * 1.5
        day = compute_auto_fare_inr(rule, distance_km=2.0, local_time_hhmm="10:00")
        assert day == 36.0

        decision = apply_fare_rules(
            mode="auto_rickshaw",
            operator="street_auto",
            passenger_profile={"vehicle_type": "auto_rickshaw"},
            distance_km=3.0,
            local_time_hhmm="23:30",
            rules=[rule],
        )
        assert decision.status == "applied"
        assert decision.fare_inr == 81.0  # 54 * 1.5
        notes = (decision.provenance or {}).get("quality_notes") or ""
        assert "not" in notes.lower() and "uber" in notes.lower()

    def test_sync_seed(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_auto_fare_sync_pipeline(repo, AUTO_SEED).run(version="auto-v1")
        assert result.success
        rules = repo.get_fare_rules(network="bengaluru_auto")
        assert len(rules) == 1
        assert rules[0].provenance.source_type == SourceType.GOVERNMENT_REGULATED


class TestShaktiEligibility:
    def _rules(self):
        return [build_shakti_fare_rule(), build_auto_fare_rule()]

    def test_eligible_passenger_zero_fare(self):
        decision = apply_fare_rules(
            mode="bus",
            operator="BMTC",
            service_class="ordinary",
            passenger_profile={
                "domicile": "Karnataka",
                "passenger_category": "woman",
                "operator": "BMTC",
                "service_class": "ordinary",
            },
            rules=[build_shakti_fare_rule()],
        )
        assert decision.status == "applied"
        assert decision.fare_inr == 0.0
        assert decision.rule_id == "karnataka_shakti_zero_fare_v1"

    def test_ineligible_passenger_not_zero(self):
        decision = apply_fare_rules(
            mode="bus",
            operator="BMTC",
            service_class="ordinary",
            passenger_profile={
                "domicile": "Karnataka",
                "passenger_category": "man",
                "service_class": "ordinary",
            },
            rules=[build_shakti_fare_rule()],
        )
        assert decision.fare_inr != 0.0
        assert decision.status == "no_matching_rule"

    def test_excluded_service_not_zero(self):
        decision = apply_fare_rules(
            mode="bus",
            operator="BMTC",
            service_class="ac",
            passenger_profile={
                "domicile": "Karnataka",
                "passenger_category": "woman",
                "service_class": "ac",
            },
            rules=[build_shakti_fare_rule()],
        )
        assert decision.fare_inr != 0.0
        assert decision.status in {"no_matching_rule", "ineligible"}

    def test_insufficient_profile_does_not_assume(self):
        decision = apply_fare_rules(
            mode="bus",
            operator="BMTC",
            service_class="ordinary",
            passenger_profile={
                # missing domicile
                "passenger_category": "woman",
                "service_class": "ordinary",
            },
            rules=[build_shakti_fare_rule()],
        )
        assert decision.status == "insufficient_profile"
        assert decision.fare_inr is None

    def test_sync_seed(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        result = build_shakti_sync_pipeline(repo, SHAKTI_SEED).run(version="shakti-v1")
        assert result.success
        rules = repo.get_fare_rules(provider="Government_of_Karnataka")
        assert rules
        assert rules[0].eligibility
        assert rules[0].provenance.source_url


class TestRegistryPhase5B:
    def test_four_datasets_configured_with_authority(self):
        bmtc = get_dataset("bmtc_network")
        assert bmtc.currently_configured and not bmtc.claimed_official
        assert "COMMUNITY" in bmtc.authority_or_source or "community" in bmtc.notes.lower()

        bmrcl = get_dataset("bmrcl_metro_network")
        assert bmrcl.currently_configured and bmrcl.claimed_official

        auto = get_dataset("transit_fare_rules")
        assert auto.currently_configured
        assert "GOVERNMENT_REGULATED" in auto.authority_or_source

        shakti = get_dataset("government_concession_rules")
        assert shakti.currently_configured and shakti.claimed_official


class TestSyncFailureBehavior:
    def test_invalid_snapshot_does_not_replace_active(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        good = build_bmrcl_sync_pipeline(repo, BMRCL_SEED).run(version="good")
        assert good.success
        assert repo.get_active_snapshot("bmrcl").version == "good"
        checksum = repo.get_active_snapshot("bmrcl").checksum

        bad_payload = {
            "stops": [],
            "stations": [],
            "routes": [],
            "fare_rules": [],
        }
        bad = SyncPipeline(
            source=LocalDictDataSource(
                name="bmrcl",
                provider_name="BMRCL",
                source_label="bmrcl_official_web_normalized",
            ),
            fetcher=StaticDictFetcher(bad_payload),
            parser=PassthroughParser(),
            normalizer=IdentityNormalizer(),
            repository=repo,
            source_type=SourceType.OFFICIAL_OPEN_DATA,
            source_url="https://english.bmrc.co.in/schematic-route-map/",
        ).run(version="bad-empty")
        assert bad.success is False
        assert bad.published is False
        active = repo.get_active_snapshot("bmrcl")
        assert active.version == "good"
        assert active.checksum == checksum
        assert active.provenance.source_type == SourceType.OFFICIAL_OPEN_DATA
        failed = tmp_path / "bmrcl" / "failed" / "bad-empty.json"
        assert failed.exists()
        assert active.validation_status == ValidationStatus.PUBLISHED
