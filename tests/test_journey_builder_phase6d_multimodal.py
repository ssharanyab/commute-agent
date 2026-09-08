"""
Phase 6D multimodal — diversity retention + search accounting.
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
from src.journey_builder.diversity import (
    audit_mode_signature,
    collapse_mode_tokens,
    select_diverse_journeys,
)
from src.journey_builder.models import (
    EdgeKind,
    Journey,
    JourneyLeg,
    SegmentRole,
)
from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import (
    DataProvenance,
    MobilityMode,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)
from src.network.sync.validation import assert_no_hardcoded_journeys
import src.journey_builder.builder as builder_mod
import src.journey_builder.diversity as diversity_mod


def _prov() -> dict:
    return DataProvenance(
        source="synthetic_test",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime.now(timezone.utc),
        version="t1",
        confidence=0.9,
    ).to_dict()


def _publish(repo, dataset, payload, version="v1"):
    snap = MobilityNetworkSnapshot(
        dataset_name=dataset,
        provider="test",
        version=version,
        fetched_at=datetime.now(timezone.utc),
        record_count=1,
        source="synthetic_test",
        validation_status=ValidationStatus.VALID,
        provenance=DataProvenance.from_dict(_prov()),
        checksum="test",
        payload=payload,
    )
    repo.publish_snapshot(snap)


def _metro_bus_transfer_payload():
    """Bus near metro M0; metro M0→M2; dest near M2 — enables bus↔metro."""
    p = _prov()
    return {
        "stops": [
            {
                "id": "B0",
                "name": "Bus near M0",
                "latitude": 12.9002,
                "longitude": 77.6001,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "provenance": p,
            },
            {
                "id": "B1",
                "name": "Bus mid",
                "latitude": 12.9102,
                "longitude": 77.6001,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "provenance": p,
            },
        ],
        "stations": [
            {
                "id": "M0",
                "name": "Metro 0",
                "latitude": 12.9000,
                "longitude": 77.6000,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 0},
                "interchange_station_ids": [],
                "provenance": p,
            },
            {
                "id": "M1",
                "name": "Metro 1",
                "latitude": 12.9100,
                "longitude": 77.6000,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 1},
                "interchange_station_ids": [],
                "provenance": p,
            },
            {
                "id": "M2",
                "name": "Metro 2",
                "latitude": 12.9200,
                "longitude": 77.6000,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 2},
                "interchange_station_ids": [],
                "provenance": p,
            },
        ],
        "routes": [
            {
                "id": "BUS1",
                "name": "Bus1",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["B0", "B1"],
                "provenance": p,
            },
            {
                "id": "purple",
                "name": "Purple",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "stop_ids": ["M0", "M1", "M2"],
                "provenance": p,
            },
        ],
        "fare_rules": [],
    }


@pytest.fixture
def multi_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    payload = _metro_bus_transfer_payload()
    # Split publish: BMTC stops+bus route; BMRCL stations+metro
    _publish(
        repo,
        "bmtc",
        {
            "stops": payload["stops"],
            "stations": [],
            "routes": [payload["routes"][0]],
            "fare_rules": [],
        },
    )
    _publish(
        repo,
        "bmrcl",
        {
            "stops": [],
            "stations": payload["stations"],
            "routes": [payload["routes"][1]],
            "fare_rules": [],
        },
    )
    return repo


def _journey(modes, route_ids=None) -> Journey:
    legs = []
    for i, m in enumerate(modes):
        mode = {
            "walk": MobilityMode.WALK,
            "bus": MobilityMode.BUS,
            "metro": MobilityMode.METRO,
            "cab": MobilityMode.CAB,
            "auto_rickshaw": MobilityMode.AUTO_RICKSHAW,
        }[m]
        rid = None
        if route_ids and i < len(route_ids):
            rid = route_ids[i]
        legs.append(
            JourneyLeg(
                index=i,
                mode=mode,
                from_node_id=f"n{i}",
                to_node_id=f"n{i+1}",
                edge_id=f"e{i}",
                edge_kind=EdgeKind.WALK,
                route_id=rid,
            )
        )
    return Journey(
        candidate_id="c",
        origin=(0, 0),
        destination=(1, 1),
        legs=legs,
        transfer_count=0,
        walking_distance_meters=0,
        transit_leg_count=0,
        road_leg_count=0,
        modes=list(modes),
        snapshot_versions={},
        provenance_sources=[],
    )


class TestSignaturesAndDiversity:
    def test_audit_signature_normalizes_bus_and_auto(self):
        assert audit_mode_signature(["walk", "bus", "walk"]) == "walk → bmtc → walk"
        assert (
            audit_mode_signature(["auto_rickshaw", "metro", "walk"])
            == "auto → metro → walk"
        )
        assert collapse_mode_tokens(["bus", "bus", "metro"]) == ("bmtc", "metro")

    def test_diverse_selection_preserves_distinct_signatures(self):
        pool = [
            _journey(["walk", "bus", "walk"], ["R1"]),
            _journey(["walk", "bus", "walk"], ["R2"]),
            _journey(["walk", "bus", "walk"], ["R3"]),
            _journey(["walk", "bus", "walk"], ["R4"]),
            _journey(["walk", "metro", "walk"], ["P"]),
            _journey(["cab"]),
            _journey(["auto_rickshaw"]),
        ]
        selected, meta = select_diverse_journeys(
            pool, max_candidates=5, per_signature=2
        )
        sigs = {audit_mode_signature(j.modes) for j in selected}
        assert "walk → metro → walk" in sigs
        assert "cab" in sigs or "auto" in sigs
        assert meta["diverse_selected"] == 5
        # Not more than per_signature of the bus class
        busish = [
            j
            for j in selected
            if audit_mode_signature(j.modes) == "walk → bmtc → walk"
        ]
        assert len(busish) <= 2

    def test_no_hardcoded_templates(self):
        assert_no_hardcoded_journeys(vars(builder_mod))
        assert_no_hardcoded_journeys(vars(diversity_mod))


class TestSearchAccounting:
    def test_counters_present(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=12.8992,
                origin_lon=77.6000,
                destination_lat=12.9208,
                destination_lon=77.6000,
                departure_time=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
                search_limits=SearchLimits(
                    allow_road_access=True,
                    allow_direct_road=True,
                    max_candidates=20,
                    max_nodes_explored=3000,
                ),
            )
        )
        meta = result.search_metadata
        for key in (
            "nodes_explored",
            "edges_considered",
            "candidates_generated",
            "candidates_retained",
            "dominance_pruned",
            "constraint_pruned",
            "leg_limit_pruned",
            "dest_reaches",
            "metro_containing_generated",
        ):
            assert key in meta
        assert meta["candidates_retained"] == len(result.candidates)
        assert meta["candidates_retained"] <= 20

    def test_road_direct_and_metro_and_exclusion(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        limits = SearchLimits(
            allow_road_access=True,
            allow_direct_road=True,
            max_candidates=20,
            max_nodes_explored=3000,
        )
        result = builder.build(
            JourneyBuildRequest(
                12.8992,
                77.6000,
                12.9208,
                77.6000,
                datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
                JourneyConstraints(),
                limits,
            )
        )
        assert any(
            any(l.edge_kind == EdgeKind.ROAD_DIRECT for l in c.legs)
            or c.modes in (["cab"], ["auto_rickshaw"])
            for c in result.candidates
        )
        assert any("metro" in c.modes for c in result.candidates)

        no_cab = builder.build(
            JourneyBuildRequest(
                12.8992,
                77.6000,
                12.9208,
                77.6000,
                datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
                JourneyConstraints(excluded_modes=["cab"]),
                limits,
            )
        )
        for c in no_cab.candidates:
            assert "cab" not in c.modes


class TestMetroMetroSynthetic:
    def test_metro_line_traversal(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            JourneyBuildRequest(
                12.8992,
                77.6000,
                12.9208,
                77.6000,
                datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
                search_limits=SearchLimits(
                    allow_road_access=False,
                    allow_direct_road=False,
                    max_candidates=20,
                    max_nodes_explored=2000,
                ),
            )
        )
        metro = [c for c in result.candidates if "metro" in c.modes]
        assert metro
        assert any(
            any(l.route_id == "purple" for l in c.legs) for c in metro
        )
