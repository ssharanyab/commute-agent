"""
Phase 5C — Dynamic Journey Builder tests (synthetic networks + real-data load).
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.journey_builder as jb_pkg
import src.journey_builder.builder as builder_mod
import src.journey_builder.graph as graph_mod
from src.journey_builder import (
    DynamicJourneyBuilder,
    JourneyBuildRequest,
    JourneyConstraints,
    SearchLimits,
    build_mobility_graph,
)
from src.journey_builder.models import EdgeKind, NodeKind
from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmrcl import build_bmrcl_sync_pipeline
from src.network.ingest.bmtc_gtfs import build_bmtc_sync_pipeline
from src.network.models import (
    DataProvenance,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)
from src.network.sync.validation import assert_no_hardcoded_journeys


def _prov() -> dict:
    return DataProvenance(
        source="synthetic_test",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime.now(timezone.utc),
        version="t1",
        confidence=0.9,
    ).to_dict()


def _publish(repo: FileStaticMobilityRepository, dataset: str, payload: dict, version: str = "v1"):
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


def _req(olat, olon, dlat, dlon, **kwargs) -> JourneyBuildRequest:
    return JourneyBuildRequest(
        origin_lat=olat,
        origin_lon=olon,
        destination_lat=dlat,
        destination_lon=dlon,
        departure_time=kwargs.get(
            "departure_time", datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)
        ),
        constraints=kwargs.get("constraints", JourneyConstraints()),
        search_limits=kwargs.get("search_limits", SearchLimits(
            max_walking_access_meters=500,
            max_walking_egress_meters=500,
            max_direct_walk_meters=1500,
            max_road_access_meters=3000,
            max_transfers=3,
            max_legs=8,
            max_candidates=20,
            allow_road_access=True,
        )),
    )


def _modes_seq(journey) -> list:
    return [leg.mode.value for leg in journey.legs]


# ---------------------------------------------------------------------------
# Synthetic network fixtures
# ---------------------------------------------------------------------------


def _bus_payload():
    p = _prov()
    return {
        "stops": [
            {
                "id": "B1",
                "name": "Bus One",
                "latitude": 12.9700,
                "longitude": 77.5900,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "B2",
                "name": "Bus Two",
                "latitude": 12.9750,
                "longitude": 77.5950,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "B3",
                "name": "Bus Three",
                "latitude": 12.9800,
                "longitude": 77.6000,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "stations": [],
        "routes": [
            {
                "id": "R1",
                "name": "Route R1",
                "short_name": "R1",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["B1", "B2"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "R2",
                "name": "Route R2",
                "short_name": "R2",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["B2", "B3"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "RGHOST",
                "name": "Ghost",
                "short_name": "G",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": [],
                "geometry_ref": None,
                "service_metadata": {"operational_status": "unknown"},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "fare_rules": [],
    }


def _metro_payload():
    p = _prov()
    return {
        "stops": [],
        "stations": [
            {
                "id": "M1",
                "name": "Metro One",
                "latitude": 12.9710,
                "longitude": 77.5910,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 1},
                "interchange_station_ids": [],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "M2",
                "name": "Metro Two",
                "latitude": 12.9760,
                "longitude": 77.5960,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 2},
                "interchange_station_ids": [],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "routes": [
            {
                "id": "purple",
                "name": "Purple Line",
                "short_name": "Purple",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "stop_ids": ["M1", "M2"],
                "geometry_ref": None,
                "service_metadata": {"color": "#800080"},
                "source_metadata": {},
                "provenance": p,
            }
        ],
        "fare_rules": [],
    }


def _multimodal_payload():
    """Bus B1→B2 near metro M1; metro M1→M2; walk transfer B2↔M1."""
    p = _prov()
    return {
        "stops": [
            {
                "id": "B1",
                "name": "Bus Near Origin",
                "latitude": 12.9700,
                "longitude": 77.5900,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "B2",
                "name": "Bus Near Metro",
                "latitude": 12.9748,
                "longitude": 77.5958,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "stations": [
            {
                "id": "M1",
                "name": "Metro Hub",
                "latitude": 12.9750,
                "longitude": 77.5960,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 1},
                "interchange_station_ids": [],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "M2",
                "name": "Metro End",
                "latitude": 12.9850,
                "longitude": 77.6100,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 2},
                "interchange_station_ids": [],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "routes": [
            {
                "id": "R1",
                "name": "Bus R1",
                "short_name": "R1",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["B1", "B2"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "purple",
                "name": "Purple",
                "short_name": "P",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "stop_ids": ["M1", "M2"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "fare_rules": [],
    }


@pytest.fixture
def bus_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish(repo, "bmtc", _bus_payload())
    return repo


@pytest.fixture
def metro_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish(repo, "bmrcl", _metro_payload())
    return repo


@pytest.fixture
def multi_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish(repo, "network", _multimodal_payload())
    return repo


class TestNoHardcodedTemplates:
    def test_no_journey_template_constants(self):
        assert_no_hardcoded_journeys(vars(jb_pkg))
        assert_no_hardcoded_journeys(vars(builder_mod))
        assert_no_hardcoded_journeys(vars(graph_mod))
        for mod in (jb_pkg, builder_mod, graph_mod):
            src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
            assert not re.search(r"^\s*ALLOWED_JOURNEYS\s*=", src, re.M)
            assert not re.search(r"^\s*SUPPORTED_COMBINATIONS\s*=", src, re.M)
            assert not re.search(r"^\s*AUTO_METRO_WALK\s*=", src, re.M)
            assert not re.search(r"^\s*BUS_METRO_WALK\s*=", src, re.M)
            assert "FIXED_JOURNEY_COMBINATIONS" not in src
            assert "HARDCODED_JOURNEYS" not in src


class TestWalkingOnly:
    def test_direct_walk(self, tmp_path: Path):
        repo = FileStaticMobilityRepository(tmp_path)
        builder = DynamicJourneyBuilder(repo)
        result = builder.build(
            _req(12.97, 77.59, 12.971, 77.591, search_limits=SearchLimits(
                max_direct_walk_meters=500,
                allow_road_access=False,
                max_candidates=5,
            ))
        )
        assert result.candidates
        assert any(_modes_seq(c) == ["walk"] for c in result.candidates)


class TestBusOnly:
    def test_walk_bus_walk(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        # Origin near B1, dest near B2
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9752,
                77.5952,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    allow_road_access=False,
                    max_candidates=10,
                ),
            )
        )
        assert result.candidates
        match = [
            c
            for c in result.candidates
            if "bus" in c.modes and c.legs
        ]
        assert match
        journey = match[0]
        assert any(leg.route_id == "R1" for leg in journey.legs)
        assert any(leg.from_ref == "B1" or leg.to_ref == "B1" for leg in journey.legs)
        assert any(leg.from_ref == "B2" or leg.to_ref == "B2" for leg in journey.legs)
        assert "synthetic_test" in journey.provenance_sources or journey.provenance_sources


class TestMetroOnly:
    def test_walk_metro_walk(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.9708,
                77.5908,
                12.9762,
                77.5962,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    allow_road_access=False,
                ),
            )
        )
        assert any("metro" in c.modes for c in result.candidates)
        j = next(c for c in result.candidates if "metro" in c.modes)
        assert any(leg.route_id == "purple" for leg in j.legs)
        assert any(leg.from_ref == "M1" or leg.to_ref == "M1" for leg in j.legs)


class TestBusBus:
    def test_bus_to_bus_transfer(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9802,
                77.6002,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    allow_road_access=False,
                    max_transfers=2,
                ),
            )
        )
        multi = [c for c in result.candidates if c.transfer_count >= 1 and c.transit_leg_count >= 2]
        assert multi, "expected discovered bus→bus path via B2"
        assert any(
            {leg.route_id for leg in c.legs if leg.route_id} >= {"R1", "R2"}
            for c in multi
        )


class TestMultimodal:
    def test_bus_metro_walk(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    max_walk_transfer_meters=100,
                    allow_road_access=False,
                    max_transfers=3,
                    max_legs=10,
                ),
            )
        )
        found = [
            c
            for c in result.candidates
            if "bus" in c.modes and "metro" in c.modes
        ]
        assert found, "bus→metro should be discovered from topology"
        j = found[0]
        assert j.transfer_count >= 1
        refs = {leg.from_ref for leg in j.legs} | {leg.to_ref for leg in j.legs}
        assert "B1" in refs or any(leg.from_ref == "B1" for leg in j.legs)
        assert "M2" in refs or any(leg.to_ref == "M2" for leg in j.legs)

    def test_multiple_possible_journeys(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                search_limits=SearchLimits(
                    max_walking_access_meters=500,
                    max_walking_egress_meters=500,
                    max_walk_transfer_meters=100,
                    max_road_access_meters=5000,
                    allow_road_access=True,
                    max_candidates=20,
                ),
            )
        )
        assert len(result.candidates) >= 2


class TestConstraints:
    def test_max_transfer_constraint(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9802,
                77.6002,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    allow_road_access=False,
                    max_transfers=0,
                ),
            )
        )
        assert all(c.transfer_count == 0 for c in result.candidates)
        # R1+R2 path requires a transfer — must not appear
        assert not any(
            {leg.route_id for leg in c.legs if leg.route_id} >= {"R1", "R2"}
            for c in result.candidates
        )

    def test_max_leg_constraint(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    max_walk_transfer_meters=100,
                    allow_road_access=False,
                    max_legs=2,
                    max_candidates=20,
                ),
            )
        )
        assert all(len(c.legs) <= 2 for c in result.candidates)

    def test_max_candidate_limit(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                search_limits=SearchLimits(
                    max_walking_access_meters=800,
                    max_walking_egress_meters=800,
                    max_walk_transfer_meters=100,
                    allow_road_access=True,
                    max_candidates=2,
                ),
            )
        )
        assert len(result.candidates) <= 2

    def test_excluded_cab(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                constraints=JourneyConstraints(excluded_modes=["cab"]),
                search_limits=SearchLimits(
                    max_walking_access_meters=500,
                    max_walking_egress_meters=500,
                    allow_road_access=True,
                    max_road_access_meters=5000,
                ),
            )
        )
        for c in result.candidates:
            assert "cab" not in c.modes
            # Cab family ≠ auto: excluding cab must not remove auto_rickshaw.

    def test_excluded_bus(self, multi_repo):
        builder = DynamicJourneyBuilder(multi_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9852,
                77.6102,
                constraints=JourneyConstraints(excluded_modes=["bus"]),
                search_limits=SearchLimits(
                    max_walking_access_meters=1000,
                    max_walking_egress_meters=500,
                    max_walk_transfer_meters=100,
                    allow_road_access=False,
                ),
            )
        )
        assert all("bus" not in c.modes for c in result.candidates)
        assert any("metro" in c.modes for c in result.candidates)


class TestPruningAndMeta:
    def test_dominance_pruning_recorded(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(
                12.9698,
                77.5898,
                12.9752,
                77.5952,
                search_limits=SearchLimits(
                    max_walking_access_meters=400,
                    max_walking_egress_meters=400,
                    allow_road_access=True,
                ),
            )
        )
        assert "candidates_pruned" in result.search_metadata
        assert result.search_metadata["nodes_explored"] > 0

    def test_snapshot_version_survives(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(12.9698, 77.5898, 12.9752, 77.5952)
        )
        assert result.network_snapshot_versions.get("bmtc") == "v1"
        if result.candidates:
            assert result.candidates[0].snapshot_versions.get("bmtc") == "v1"

    def test_provenance_survives(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(12.9698, 77.5898, 12.9752, 77.5952)
        )
        transit = [c for c in result.candidates if c.transit_leg_count]
        assert transit
        assert any(c.provenance_sources for c in transit)

    def test_departure_time_in_metadata(self, bus_repo):
        dep = datetime(2024, 7, 4, 8, 30, tzinfo=timezone.utc)
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(12.9698, 77.5898, 12.9752, 77.5952, departure_time=dep)
        )
        assert result.search_metadata["departure_time"] == dep.isoformat()

    def test_temporal_unknown_without_schedules(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(12.9698, 77.5898, 12.9752, 77.5952)
        )
        transit = [c for c in result.candidates if c.transit_leg_count]
        assert transit
        assert all(c.temporal_feasibility == "unknown" for c in transit)

    def test_ghost_route_not_fabricated(self, bus_repo):
        graph = build_mobility_graph(bus_repo)
        assert not any(
            e.route_id == "RGHOST" for e in graph.edges.values()
        )

    def test_empty_no_path(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        result = builder.build(
            _req(
                13.5,
                77.5,
                13.6,
                77.6,
                search_limits=SearchLimits(
                    max_walking_access_meters=50,
                    max_walking_egress_meters=50,
                    max_direct_walk_meters=50,
                    max_road_access_meters=50,
                    allow_road_access=False,
                ),
            )
        )
        assert result.candidates == []
        assert any("NO_PATH" in w for w in result.warnings)

    def test_deterministic(self, bus_repo):
        builder = DynamicJourneyBuilder(bus_repo)
        req = _req(12.9698, 77.5898, 12.9752, 77.5952)
        a = builder.build(req)
        b = builder.build(req)
        assert [c.candidate_id for c in a.candidates] == [
            c.candidate_id for c in b.candidates
        ]
        assert [c.to_dict() for c in a.candidates] == [
            c.to_dict() for c in b.candidates
        ]


class TestRealDataIntegration:
    def test_phase5b_repo_to_journey_builder(self, tmp_path: Path):
        """
        Phase 5B repository → graph → candidate journey (no network access).

        Uses BMTC sample fixture (coords) + BMRCL seed (topology; stations may
        lack coordinates so metro access/egress via walk may be unavailable).
        """
        repo = FileStaticMobilityRepository(tmp_path)
        fixture = (
            Path(__file__).parent / "fixtures" / "bmtc_gtfs_sample"
        )
        bmtc = build_bmtc_sync_pipeline(fixture, repo).run(version="bmtc-sample")
        assert bmtc.success
        seed = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "mobility_network"
            / "bmrcl"
            / "seed"
            / "bmrcl_network_seed.json"
        )
        bmrcl = build_bmrcl_sync_pipeline(repo, seed).run(version="bmrcl-seed")
        assert bmrcl.success

        graph = build_mobility_graph(repo)
        assert graph.stats()["bus_stops"] >= 2
        assert graph.stats()["metro_stations"] >= 1
        assert graph.snapshot_versions.get("bmtc") == "bmtc-sample"
        assert graph.snapshot_versions.get("bmrcl") == "bmrcl-seed"
        # Metro line edges exist even without coordinates
        assert any(e.kind == EdgeKind.METRO for e in graph.edges.values())
        assert any(e.kind == EdgeKind.BUS for e in graph.edges.values())

        # Journey using BMTC sample stop coords (S1→S2)
        builder = DynamicJourneyBuilder(repo, graph=graph)
        result = builder.build(
            _req(
                12.9770,
                77.5720,
                12.9784,
                77.6408,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    max_direct_walk_meters=100,  # force transit preference path
                    allow_road_access=False,
                ),
            )
        )
        assert result.network_snapshot_versions
        # Either walk-bus-walk or direct walk depending on distances;
        # at minimum graph loaded and search ran.
        assert result.search_metadata["nodes_explored"] > 0
        bus_journeys = [c for c in result.candidates if "bus" in c.modes]
        # S1 and S2 are ~7.5km apart — direct walk disabled; access at stops.
        assert bus_journeys, (
            "Expected BMTC sample route journey; limitation only if fixture "
            "stop sequence missing"
        )
        j = bus_journeys[0]
        assert any(leg.route_id == "R500" for leg in j.legs)
        assert j.snapshot_versions.get("bmtc") == "bmtc-sample"
