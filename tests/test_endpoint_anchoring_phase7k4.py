"""
Phase 7K-4 — Endpoint mobility-node anchoring (fixture regression).

Generic fixtures only — no production OD name hardcoding in assertions
beyond published node ids used as fixture identifiers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.journey_builder import (
    DynamicJourneyBuilder,
    EndpointResolutionError,
    JourneyBuildRequest,
    JourneyConstraints,
    JourneyEndpoint,
    SearchLimits,
)
from src.journey_builder.builder import ORIGIN_ID, DEST_ID
from src.journey_builder.diversity import collapse_mode_tokens
from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import (
    DataProvenance,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)


def _prov() -> dict:
    return DataProvenance(
        source="synthetic_test",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime.now(timezone.utc),
        version="t7k4",
        confidence=0.9,
    ).to_dict()


def _publish(repo: FileStaticMobilityRepository, dataset: str, payload: dict, version: str):
    snap = MobilityNetworkSnapshot(
        dataset_name=dataset,
        provider="test",
        version=version,
        fetched_at=datetime.now(timezone.utc),
        record_count=sum(len(payload.get(k) or []) for k in ("stops", "stations", "routes")),
        source="synthetic_test",
        validation_status=ValidationStatus.VALID,
        provenance=DataProvenance.from_dict(_prov()),
        checksum="test",
        payload=payload,
    )
    repo.publish_snapshot(snap)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> FileStaticMobilityRepository:
    repo = FileStaticMobilityRepository(tmp_path)
    p = _prov()
    # Two metro stations ~1.1km apart + two bus stops on a short route.
    _publish(
        repo,
        "bmrcl",
        {
            "stations": [
                {
                    "id": "sta_a",
                    "name": "Station A",
                    "latitude": 12.9700,
                    "longitude": 77.5800,
                    "provider": "BMRCL",
                    "network": "bmrcl",
                    "lines": ["L1"],
                    "line_order": {"L1": 1},
                    "provenance": p,
                },
                {
                    "id": "sta_b",
                    "name": "Station B",
                    "latitude": 12.9700,
                    "longitude": 77.5900,
                    "provider": "BMRCL",
                    "network": "bmrcl",
                    "lines": ["L1"],
                    "line_order": {"L1": 2},
                    "provenance": p,
                },
            ],
            "routes": [
                {
                    "id": "L1",
                    "name": "Line 1",
                    "mode": "metro",
                    "provider": "BMRCL",
                    "network": "bmrcl",
                    "stop_ids": ["sta_a", "sta_b"],
                    "provenance": p,
                }
            ],
            "stops": [],
            "fare_rules": [],
        },
        "v1",
    )
    _publish(
        repo,
        "bmtc",
        {
            "stops": [
                {
                    "id": "bus_a",
                    "name": "Bus A",
                    "latitude": 12.9600,
                    "longitude": 77.5800,
                    "provider": "BMTC",
                    "network": "bmtc",
                    "provenance": p,
                },
                {
                    "id": "bus_b",
                    "name": "Bus B",
                    "latitude": 12.9600,
                    "longitude": 77.5850,
                    "provider": "BMTC",
                    "network": "bmtc",
                    "provenance": p,
                },
            ],
            "routes": [
                {
                    "id": "R1",
                    "name": "Route 1",
                    "mode": "bus",
                    "provider": "BMTC",
                    "network": "bmtc",
                    "stop_ids": ["bus_a", "bus_b"],
                    "provenance": p,
                }
            ],
            "stations": [],
            "fare_rules": [],
        },
        "v1",
    )
    return repo


def _zero_access_to(journeys, node_id: str) -> list:
    bad = []
    for j in journeys:
        for leg in j.legs:
            if leg.to_node_id == node_id and leg.from_node_id == ORIGIN_ID:
                if float(leg.distance_meters or 0) <= 0.5:
                    bad.append((j.mode_signature, leg.mode.value, "access"))
            if leg.from_node_id == node_id and leg.to_node_id == DEST_ID:
                if float(leg.distance_meters or 0) <= 0.5:
                    bad.append((j.mode_signature, leg.mode.value, "egress"))
    return bad


class TestPhase7K4EndpointAnchoring:
    def test_station_to_station_no_zero_access(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        o = JourneyEndpoint.network_node(
            network="bmrcl",
            node_id="station:sta_a",
            lat=12.9700,
            lon=77.5800,
        )
        d = JourneyEndpoint.network_node(
            network="bmrcl",
            node_id="station:sta_b",
            lat=12.9700,
            lon=77.5900,
        )
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9700,
                origin_lon=77.5800,
                destination_lat=12.9700,
                destination_lon=77.5900,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                origin_endpoint=o,
                destination_endpoint=d,
            )
        )
        assert result.candidates
        sigs = {j.mode_signature for j in result.candidates}
        assert any(s == "metro" or s.startswith("metro") for s in sigs)
        # No access:origin / access:destination zero legs to anchored stations.
        assert _zero_access_to(result.candidates, "station:sta_a") == []
        assert _zero_access_to(result.candidates, "station:sta_b") == []
        metro = next(j for j in result.candidates if "metro" in j.modes)
        assert metro.legs[0].from_node_id == "station:sta_a"
        assert metro.legs[-1].to_node_id == "station:sta_b"
        assert metro.legs[0].from_node_id != ORIGIN_ID
        assert metro.legs[-1].to_node_id != DEST_ID

    def test_station_to_place_has_egress_not_access(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        o = JourneyEndpoint.network_node(
            network="bmrcl", node_id="station:sta_a", lat=12.9700, lon=77.5800
        )
        # Place near station B (~110m east of B).
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9700,
                origin_lon=77.5800,
                destination_lat=12.9700,
                destination_lon=77.5910,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                origin_endpoint=o,
                destination_endpoint=JourneyEndpoint.place(
                    lat=12.9700, lon=77.5910, display_name="Near B"
                ),
            )
        )
        assert result.candidates
        metroish = [
            j
            for j in result.candidates
            if "metro" in collapse_mode_tokens(tuple(j.modes))
        ]
        assert metroish
        for j in metroish:
            assert j.legs[0].from_node_id == "station:sta_a"
            assert j.legs[0].from_node_id != ORIGIN_ID
            assert any(l.to_node_id == DEST_ID for l in j.legs)

    def test_place_to_station_has_access_not_egress(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        d = JourneyEndpoint.network_node(
            network="bmrcl", node_id="station:sta_b", lat=12.9700, lon=77.5900
        )
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9700,
                origin_lon=77.5790,  # near A
                destination_lat=12.9700,
                destination_lon=77.5900,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                origin_endpoint=JourneyEndpoint.place(lat=12.9700, lon=77.5790),
                destination_endpoint=d,
            )
        )
        assert result.candidates
        metroish = [
            j
            for j in result.candidates
            if "metro" in collapse_mode_tokens(tuple(j.modes))
        ]
        assert metroish
        for j in metroish:
            assert j.legs[0].from_node_id == ORIGIN_ID
            assert j.legs[-1].to_node_id == "station:sta_b"
            assert j.legs[-1].to_node_id != DEST_ID

    def test_place_to_place_keeps_access_discovery(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9700,
                origin_lon=77.5790,
                destination_lat=12.9700,
                destination_lon=77.5910,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
            )
        )
        assert result.candidates
        walk_metro = [
            j
            for j in result.candidates
            if collapse_mode_tokens(tuple(j.modes))[:1] == ("walk",)
            and "metro" in j.modes
        ]
        assert walk_metro
        assert any(l.from_node_id == ORIGIN_ID for j in walk_metro for l in j.legs)
        assert any(l.to_node_id == DEST_ID for j in walk_metro for l in j.legs)

    def test_stop_to_stop_no_zero_access(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        o = JourneyEndpoint.network_node(
            network="bmtc", node_id="stop:bus_a", lat=12.9600, lon=77.5800
        )
        d = JourneyEndpoint.network_node(
            network="bmtc", node_id="stop:bus_b", lat=12.9600, lon=77.5850
        )
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.9600,
                origin_lon=77.5800,
                destination_lat=12.9600,
                destination_lon=77.5850,
                departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                origin_endpoint=o,
                destination_endpoint=d,
            )
        )
        assert result.candidates
        assert _zero_access_to(result.candidates, "stop:bus_a") == []
        assert _zero_access_to(result.candidates, "stop:bus_b") == []
        bus = next(j for j in result.candidates if "bus" in j.modes)
        assert bus.legs[0].from_node_id == "stop:bus_a"
        assert bus.legs[-1].to_node_id == "stop:bus_b"

    def test_unknown_network_node_errors(self, tmp_repo):
        builder = DynamicJourneyBuilder(tmp_repo)
        with pytest.raises(EndpointResolutionError) as ei:
            builder.build(
                JourneyBuildRequest(
                    origin_lat=12.97,
                    origin_lon=77.58,
                    destination_lat=12.97,
                    destination_lon=77.59,
                    departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
                    origin_endpoint=JourneyEndpoint.network_node(
                        network="bmrcl",
                        node_id="station:does_not_exist",
                        lat=12.97,
                        lon=77.58,
                    ),
                )
            )
        assert ei.value.code == "UNKNOWN_NETWORK_NODE"
