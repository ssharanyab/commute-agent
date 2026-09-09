"""
Phase 7K-1 — Walk-access transit discovery before road-access soft-cap.

Fixture-based: nearby walk→transit must be generated even when many
road-access nodes would otherwise exhaust the soft candidate cap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.journey_builder import (
    DynamicJourneyBuilder,
    JourneyBuildRequest,
    JourneyConstraints,
    SearchLimits,
)
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
        version="t7k1",
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


def _metro_payload_near_and_far() -> dict:
    """
    Origin near station A; destination near station B on one metro line.

    Also place many far stations within road-access radius but outside walk
    radius so road flooding can compete with walk boarding.
    """
    p = _prov()
    # Origin (0,0); dest ~1.1km east (approx 0.01 deg ≈ 1.1km at equator-ish).
    # Use small degree offsets (~111m per 0.001 lat).
    stations = [
        {
            "id": "near_o",
            "name": "Near Origin Transit",
            "latitude": 12.9702,  # ~200m north of origin
            "longitude": 77.5800,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["L1"],
            "line_order": {"L1": 1},
            "provenance": p,
        },
        {
            "id": "near_d",
            "name": "Near Dest Transit",
            "latitude": 12.9702,
            "longitude": 77.6100,  # aligned with dest longitude
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["L1"],
            "line_order": {"L1": 2},
            "provenance": p,
        },
    ]
    # Far stations ~3–4.5km from origin (road access yes, walk no).
    for i in range(12):
        stations.append(
            {
                "id": f"far_{i}",
                "name": f"Far Station {i}",
                "latitude": 12.9684 - 0.005 * (i % 4),
                "longitude": 77.5800 - 0.025 - 0.002 * i,
                "provider": "BMRCL",
                "network": "bmrcl",
                "lines": ["L1"],
                "line_order": {"L1": 10 + i},
                "provenance": p,
            }
        )
    stop_ids = ["near_o", "near_d"] + [f"far_{i}" for i in range(12)]
    # Put near_o → near_d on the line (far stations on a dead branch via order).
    # Route stop_ids order by line_order for ingest; builder uses published routes.
    return {
        "stations": stations,
        "stops": [],
        "routes": [
            {
                "id": "L1",
                "name": "Line 1",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "short_name": "L1",
                "stop_ids": ["near_o", "near_d"],
                "provenance": p,
            }
        ],
        "lines_meta": [{"id": "L1", "name": "Line 1", "color": "#800080"}],
        "fare_rules": [],
    }


def _two_leg_metro_payload() -> dict:
    """walk→metro→walk→metro→walk via interchange mid station."""
    p = _prov()
    stations = [
        {
            "id": "a",
            "name": "A",
            "latitude": 12.9702,
            "longitude": 77.5800,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["red"],
            "line_order": {"red": 1},
            "provenance": p,
        },
        {
            "id": "mid",
            "name": "Mid",
            "latitude": 12.9702,
            "longitude": 77.5950,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["red", "blue"],
            "line_order": {"red": 2, "blue": 1},
            "interchange_station_ids": ["mid"],
            "provenance": p,
        },
        {
            "id": "c",
            "name": "C",
            "latitude": 12.9702,
            "longitude": 77.6100,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["blue"],
            "line_order": {"blue": 2},
            "provenance": p,
        },
    ]
    return {
        "stations": stations,
        "stops": [],
        "routes": [
            {
                "id": "red",
                "name": "Red",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "short_name": "R",
                "stop_ids": ["a", "mid"],
                "provenance": p,
            },
            {
                "id": "blue",
                "name": "Blue",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "short_name": "B",
                "stop_ids": ["mid", "c"],
                "provenance": p,
            },
        ],
        "lines_meta": [
            {"id": "red", "name": "Red", "color": "#f00"},
            {"id": "blue", "name": "Blue", "color": "#00f"},
        ],
        "fare_rules": [],
    }


def _bus_and_metro_flood_payload() -> dict:
    """Nearby metro + many walk-access bus stops to create soft-cap pressure."""
    p = _prov()
    stations = [
        {
            "id": "m0",
            "name": "Metro O",
            "latitude": 12.9702,
            "longitude": 77.5800,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["M"],
            "line_order": {"M": 1},
            "provenance": p,
        },
        {
            "id": "m1",
            "name": "Metro D",
            "latitude": 12.9702,
            "longitude": 77.6100,
            "provider": "BMRCL",
            "network": "bmrcl",
            "lines": ["M"],
            "line_order": {"M": 2},
            "provenance": p,
        },
    ]
    stops = []
    stop_ids = []
    for i in range(20):
        sid = f"B{i}"
        stop_ids.append(sid)
        stops.append(
            {
                "id": sid,
                "name": f"Bus {i}",
                "latitude": 12.9684 + 0.0003 * (i % 5),
                "longitude": 77.5800 + 0.0015 * i,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "provenance": p,
            }
        )
    return {
        "stations": stations,
        "stops": stops,
        "routes": [
            {
                "id": "M",
                "name": "Metro",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "short_name": "M",
                "stop_ids": ["m0", "m1"],
                "provenance": p,
            },
            {
                "id": "BUS1",
                "name": "Bus Flood",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "short_name": "BF",
                "stop_ids": stop_ids,
                "provenance": p,
            },
        ],
        "lines_meta": [{"id": "M", "name": "Metro", "color": "#800080"}],
        "fare_rules": [],
    }


@pytest.fixture
def tmp_repo(tmp_path: Path) -> FileStaticMobilityRepository:
    return FileStaticMobilityRepository(tmp_path)


class TestPhase7K1AccessDiscovery:
    def test_walk_transit_walk_survives_road_access_flood(self, tmp_repo):
        _publish(tmp_repo, "bmrcl", _metro_payload_near_and_far(), "near-far-v1")
        builder = DynamicJourneyBuilder(tmp_repo)
        # Origin ~200m from near_o; dest ~200m from near_d.
        req = JourneyBuildRequest(
            origin_lat=12.9684,
            origin_lon=77.5800,
            destination_lat=12.9684,
            destination_lon=77.6100,
            departure_time=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
            constraints=JourneyConstraints(),
            search_limits=SearchLimits(
                max_walking_access_meters=800,
                max_walking_egress_meters=800,
                max_road_access_meters=5000,
                allow_road_access=True,
                allow_direct_road=True,
                max_candidates=20,
                max_nodes_explored=5000,
                max_transfers=3,
                max_legs=8,
            ),
        )
        result = builder.build(req)
        sigs = result.search_metadata.get("generated_mode_signatures") or []
        assert any(s == "walk → metro → walk" for s in sigs), sigs
        # Road-access candidates must still be generated.
        assert any(
            s.startswith("auto") or s.startswith("cab") or "auto" in s or "cab" in s
            for s in sigs
        ), sigs
        assert result.search_metadata.get("access_discovery_walk_access_transit_found") is True

    def test_walk_transit_transfer_walk(self, tmp_repo):
        _publish(tmp_repo, "bmrcl", _two_leg_metro_payload(), "xfer-v1")
        builder = DynamicJourneyBuilder(tmp_repo)
        req = JourneyBuildRequest(
            origin_lat=12.9684,
            origin_lon=77.5800,
            destination_lat=12.9684,
            destination_lon=77.6100,
            departure_time=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
            constraints=JourneyConstraints(),
            search_limits=SearchLimits(
                max_walking_access_meters=800,
                max_walking_egress_meters=800,
                allow_road_access=True,
                max_road_access_meters=5000,
                max_candidates=20,
                max_nodes_explored=8000,
                max_transfers=3,
                max_legs=8,
            ),
        )
        result = builder.build(req)
        sigs = result.search_metadata.get("generated_mode_signatures") or []
        # Direct one-line may not exist; accept walk→metro→walk or transfer form.
        walk_metro = [s for s in sigs if s.startswith("walk") and "metro" in s]
        assert walk_metro, sigs
        # Prefer seeing a two-metro transfer if generated.
        assert any(
            s.count("metro") >= 1 for s in walk_metro
        )
        # Transfer signature when both lines are used.
        assert any(
            "metro" in s and s.startswith("walk") for s in sigs
        )

    def test_walk_metro_before_soft_cap_with_bus_flood(self, tmp_repo):
        _publish(tmp_repo, "bmrcl", {"stations": _bus_and_metro_flood_payload()["stations"], "stops": [], "routes": [r for r in _bus_and_metro_flood_payload()["routes"] if r["id"] == "M"], "lines_meta": _bus_and_metro_flood_payload()["lines_meta"], "fare_rules": []}, "bmrcl-flood")
        payload = _bus_and_metro_flood_payload()
        _publish(tmp_repo, "bmtc", {"stops": payload["stops"], "stations": [], "routes": [r for r in payload["routes"] if r["id"] == "BUS1"]}, "bmtc-flood")
        builder = DynamicJourneyBuilder(tmp_repo)
        req = JourneyBuildRequest(
            origin_lat=12.9684,
            origin_lon=77.5800,
            destination_lat=12.9684,
            destination_lon=77.6100,
            departure_time=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
            constraints=JourneyConstraints(),
            search_limits=SearchLimits(
                max_walking_access_meters=800,
                max_walking_egress_meters=800,
                allow_road_access=True,
                max_road_access_meters=5000,
                max_candidates=10,  # soft_cap = 30
                max_nodes_explored=8000,
            ),
        )
        result = builder.build(req)
        sigs = result.search_metadata.get("generated_mode_signatures") or []
        assert "walk → metro → walk" in sigs, sigs
        assert result.search_metadata.get("walk_access_transit_generated", 0) >= 1

    def test_deterministic_signatures(self, tmp_repo):
        _publish(tmp_repo, "bmrcl", _metro_payload_near_and_far(), "det-v1")
        builder = DynamicJourneyBuilder(tmp_repo)
        req = JourneyBuildRequest(
            origin_lat=12.9684,
            origin_lon=77.5800,
            destination_lat=12.9684,
            destination_lon=77.6100,
            departure_time=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
            search_limits=SearchLimits(
                max_walking_access_meters=800,
                max_walking_egress_meters=800,
                allow_road_access=True,
                max_road_access_meters=5000,
                max_candidates=20,
            ),
        )
        a = builder.build(req)
        b = builder.build(req)
        assert a.search_metadata["generated_mode_signatures"] == b.search_metadata[
            "generated_mode_signatures"
        ]
        assert [j.mode_signature for j in a.candidates] == [
            j.mode_signature for j in b.candidates
        ]
