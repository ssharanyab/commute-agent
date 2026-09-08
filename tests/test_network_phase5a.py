"""
Phase 5A — static network contracts, registry, sync, provenance tests.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.network as network_pkg
import src.network.models as models_mod
from src.network.file_repository import FileStaticMobilityRepository
from src.network.historical import (
    HistoricalMobilityProvider,
    UberMovementHistoricalProvider,
)
from src.network.models import (
    DataProvenance,
    FareEligibilityCondition,
    FareRule,
    MobilityMode,
    MobilityNetworkSnapshot,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
    SourceType,
    StopType,
    ValidationStatus,
)
from src.network.registry import (
    DATASET_REGISTRY,
    configured_dataset_ids,
    get_dataset,
    list_datasets,
)
from src.network.repository import StaticMobilityDataRepository
from src.network.sync import (
    IdentityNormalizer,
    LocalDictDataSource,
    PassthroughParser,
    StaticDictFetcher,
    SyncPipeline,
)
from src.network.sync.validation import (
    assert_no_hardcoded_journeys,
    validate_network_payload,
)


def _prov(**kwargs) -> DataProvenance:
    base = dict(
        source="test_fixture",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime.now(timezone.utc),
        version="t1",
        source_url="https://example.test/provenance",
    )
    base.update(kwargs)
    return DataProvenance(**base)


def _sample_payload(*, bad_coord: bool = False) -> dict:
    lat = 999.0 if bad_coord else 12.9716
    prov = _prov().to_dict()
    return {
        "stops": [
            {
                "id": "stop_a",
                "name": "Stop A",
                "latitude": lat,
                "longitude": 77.5946,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {"wheelchair": True},
                "source_metadata": {"fixture": True},
                "provenance": prov,
            },
            {
                "id": "stop_b",
                "name": "Stop B",
                "latitude": 12.9750,
                "longitude": 77.6000,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": prov,
            },
        ],
        "stations": [
            {
                "id": "st_metro_1",
                "name": "Metro One",
                "latitude": 12.9760,
                "longitude": 77.6010,
                "provider": "BMRCL",
                "lines": ["Purple"],
                "interchange_station_ids": ["st_metro_2"],
                "accessibility": {"elevator": True},
                "source_metadata": {},
                "provenance": prov,
            },
            {
                "id": "st_metro_2",
                "name": "Metro Two",
                "latitude": 12.9800,
                "longitude": 77.6050,
                "provider": "BMRCL",
                "lines": ["Purple", "Green"],
                "interchange_station_ids": ["st_metro_1"],
                "accessibility": {},
                "source_metadata": {},
                "provenance": prov,
            },
        ],
        "routes": [
            {
                "id": "route_500",
                "name": "Route 500",
                "short_name": "500",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["stop_a", "stop_b"],
                "geometry_ref": None,
                "service_metadata": {"direction": "outbound"},
                "source_metadata": {},
                "provenance": prov,
            }
        ],
        "fare_rules": [
            {
                "id": "fare_bus_base",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "base_fare": 10.0,
                "currency": "INR",
                "rule_structure": {"type": "flat_base"},
                "eligibility": [
                    {
                        "attribute": "passenger_category",
                        "operator": "in",
                        "value": ["general", "student"],
                        "description": "Applies to listed categories",
                    }
                ],
                "service_exclusions": ["airport_special"],
                "effective_from": "2024-01-01T00:00:00+00:00",
                "effective_until": None,
                "version": "2024.1",
                "provenance": prov,
            }
        ],
    }


class TestDomainModels:
    def test_modes_are_atomic_not_journeys(self):
        values = {m.value for m in MobilityMode}
        assert "walk" in values and "metro" in values
        assert "auto_metro_walk" not in values
        assert "bus_metro_walk" not in values

    def test_stop_requires_provenance_roundtrip(self):
        stop = MobilityStop.from_dict(_sample_payload()["stops"][0])
        assert stop.provenance.source == "test_fixture"
        assert stop.to_dict()["provenance"]["source"] == "test_fixture"

    def test_fare_rule_uses_eligibility_not_gender_boolean(self):
        rule = FareRule(
            id="concession_example",
            provider="government",
            network="karnataka",
            mode=MobilityMode.BUS,
            provenance=_prov(source="gazette_example"),
            base_fare=0.0,
            rule_structure={"concession_scheme": "example_scheme"},
            eligibility=(
                FareEligibilityCondition(
                    attribute="scheme_enrollment",
                    operator="eq",
                    value="example_scheme",
                    description="Must be enrolled in the named scheme",
                ),
                FareEligibilityCondition(
                    attribute="valid_id_presented",
                    operator="eq",
                    value=True,
                    description="Valid ID required at boarding",
                ),
            ),
            effective_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        )
        payload = rule.to_dict()
        assert "female" not in payload
        assert "eligibility" in payload
        assert len(payload["eligibility"]) == 2
        assert payload["source"] == "gazette_example"
        assert payload["provenance"]["source"] == "gazette_example"

    def test_snapshot_version_fields(self):
        snap = MobilityNetworkSnapshot(
            dataset_name="demo",
            provider="internal",
            version="v1",
            fetched_at=datetime.now(timezone.utc),
            record_count=3,
            source="test",
            validation_status=ValidationStatus.VALID,
            provenance=_prov(),
            checksum="abc",
            payload={"stops": []},
        )
        assert snap.to_dict()["version"] == "v1"
        assert snap.to_dict()["checksum"] == "abc"


class TestNoHardcodedJourneys:
    def test_network_package_has_no_allowed_journeys(self):
        assert_no_hardcoded_journeys(vars(network_pkg))
        assert_no_hardcoded_journeys(vars(models_mod))
        src = Path(inspect.getfile(network_pkg)).read_text(encoding="utf-8")
        assert "ALLOWED_JOURNEYS" not in src
        assert "auto_metro_walk" not in src
        assert "bus_metro_walk" not in src


class TestDatasetRegistry:
    def test_registry_contains_expected_datasets(self):
        for key in (
            "bmtc_network",
            "bmrcl_metro_network",
            "transit_fare_rules",
            "government_concession_rules",
            "uber_movement_historical",
            "weather",
            "google_live_routing",
        ):
            assert key in DATASET_REGISTRY

    def test_unconfigured_sources_not_claimed_official(self):
        for ds in list_datasets():
            if not ds.currently_configured:
                assert ds.claimed_official is False

    def test_configured_ids_include_existing_pipelines(self):
        ids = set(configured_dataset_ids())
        assert "uber_movement_historical" in ids
        assert "google_live_routing" in ids
        # Phase 5B configures community BMTC GTFS (explicitly non-official).
        assert "bmtc_network" in ids
        assert get_dataset("bmtc_network").claimed_official is False
        assert "bmrcl_metro_network" in ids
        assert "transit_fare_rules" in ids
        assert "government_concession_rules" in ids

    def test_get_dataset(self):
        assert get_dataset("weather").currently_configured is False


class TestValidation:
    def test_valid_payload_ok(self):
        assert validate_network_payload(_sample_payload()) == []

    def test_invalid_coordinates_fail(self):
        errs = validate_network_payload(_sample_payload(bad_coord=True))
        assert any("STOP_INVALID_COORDINATES" in e for e in errs)

    def test_empty_payload_fails(self):
        errs = validate_network_payload({})
        assert any("EMPTY_DATASET" in e for e in errs)

    def test_unresolved_stop_ref_fails(self):
        payload = _sample_payload()
        payload["routes"][0]["stop_ids"] = ["stop_a", "missing_stop"]
        errs = validate_network_payload(payload)
        assert any("ROUTE_STOP_REF_UNRESOLVED" in e for e in errs)

    def test_fare_invalid_window(self):
        payload = _sample_payload()
        payload["fare_rules"][0]["effective_from"] = "2025-01-01T00:00:00+00:00"
        payload["fare_rules"][0]["effective_until"] = "2024-01-01T00:00:00+00:00"
        errs = validate_network_payload(payload)
        assert any("FARE_INVALID_EFFECTIVE_WINDOW" in e for e in errs)


class TestFileRepositoryAndSync:
    def test_repository_is_provider_independent_abc(self):
        assert issubclass(FileStaticMobilityRepository, StaticMobilityDataRepository)

    def test_publish_and_query(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        payload = _sample_payload()
        snap = MobilityNetworkSnapshot(
            dataset_name="bmtc_demo",
            provider="BMTC",
            version="v1",
            fetched_at=datetime.now(timezone.utc),
            record_count=5,
            source="test_fixture",
            validation_status=ValidationStatus.VALID,
            provenance=_prov(),
            checksum="x",
            payload=payload,
        )
        repo.publish_snapshot(snap)
        active = repo.get_active_snapshot("bmtc_demo")
        assert active is not None
        assert active.version == "v1"
        assert active.validation_status == ValidationStatus.PUBLISHED

        stops = repo.find_stops_near(12.9716, 77.5946, radius_meters=2000)
        assert any(s.id == "stop_a" for s in stops)
        stations = repo.find_stations_near(12.9760, 77.6010, radius_meters=2000)
        assert any(s.id == "st_metro_1" for s in stations)
        assert repo.get_route("route_500").mode == MobilityMode.BUS
        assert list(repo.get_stop_sequence("route_500")) == ["stop_a", "stop_b"]
        assert "st_metro_2" in repo.get_station_connections("st_metro_1")
        fares = repo.get_fare_rules(provider="BMTC")
        assert len(fares) == 1
        assert fares[0].provenance.source == "test_fixture"

    def test_validation_failure_preserves_previous_snapshot(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        pipeline = SyncPipeline(
            source=LocalDictDataSource(
                name="bmtc_demo",
                provider_name="BMTC",
                source_label="test_fixture",
            ),
            fetcher=StaticDictFetcher(_sample_payload()),
            parser=PassthroughParser(),
            normalizer=IdentityNormalizer(),
            repository=repo,
            source_type=SourceType.INTERNAL_DERIVED,
        )
        first = pipeline.run(version="v1")
        assert first.success and first.published
        assert repo.get_active_snapshot("bmtc_demo").version == "v1"

        bad_pipeline = SyncPipeline(
            source=LocalDictDataSource(
                name="bmtc_demo",
                provider_name="BMTC",
                source_label="test_fixture",
            ),
            fetcher=StaticDictFetcher(_sample_payload(bad_coord=True)),
            parser=PassthroughParser(),
            normalizer=IdentityNormalizer(),
            repository=repo,
            source_type=SourceType.INTERNAL_DERIVED,
        )
        second = bad_pipeline.run(version="v2_bad")
        assert second.success is False
        assert second.published is False
        assert second.previous_active_version == "v1"
        assert second.active_version == "v1"
        assert repo.get_active_snapshot("bmtc_demo").version == "v1"
        failed = tmp_path / "bmtc_demo" / "failed" / "v2_bad.json"
        assert failed.exists()

    def test_refuse_publish_invalid_status(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        snap = MobilityNetworkSnapshot(
            dataset_name="x",
            provider="x",
            version="v0",
            fetched_at=datetime.now(timezone.utc),
            record_count=0,
            source="x",
            validation_status=ValidationStatus.FAILED,
            provenance=_prov(),
            payload={},
        )
        with pytest.raises(ValueError):
            repo.publish_snapshot(snap)


class TestHistoricalProvider:
    def test_interface_and_wrapper_provenance(self, monkeypatch):
        assert issubclass(
            UberMovementHistoricalProvider, HistoricalMobilityProvider
        )

        def _fake_signal(**kwargs):
            return {
                "has_historical_coverage": True,
                "historical_expected_travel_time_minutes": 42.0,
                "signal_source": "historical_uber_movement_ml",
                "model_version": "test_artifact",
            }

        monkeypatch.setattr(
            "src.network.historical.get_historical_mobility_signal",
            _fake_signal,
        )
        provider = UberMovementHistoricalProvider(models_dir="models")
        result = provider.get_signal(
            origin_zone=1, destination_zone=2, hour=9
        )
        assert result.model_name == "uber_movement_xgboost"
        assert result.provenance.source == "historical_uber_movement_ml"
        assert result.signal["historical_expected_travel_time_minutes"] == 42.0
        assert result.provenance.source_type == SourceType.RESEARCH_DATASET
