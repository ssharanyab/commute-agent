"""
Phase 6B — goal-directed Journey Builder search (A* + route continuation).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.journey_builder.builder as builder_mod
from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.journey_builder import (
    DynamicJourneyBuilder,
    JourneyBuildRequest,
    JourneyConstraints,
    SearchLimits,
    build_mobility_graph,
)
from src.journey_builder.builder import _ALGORITHM
from src.journey_builder.models import EdgeKind, NodeKind
from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import (
    DataProvenance,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)
from src.network.sync.validation import assert_no_hardcoded_journeys


REPO_ROOT = Path(__file__).resolve().parents[1]
MOBILITY_ROOT = REPO_ROOT / "data" / "mobility_network"


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
        search_limits=kwargs.get(
            "search_limits",
            SearchLimits(
                max_walking_access_meters=500,
                max_walking_egress_meters=500,
                allow_road_access=False,
                max_transfers=3,
                max_legs=8,
                max_candidates=20,
                max_nodes_explored=5000,
            ),
        ),
    )


def _long_bus_payload(n_stops: int = 25):
    """Linear bus corridor requiring many stop hops if counted per hop."""
    p = _prov()
    # Origin near stop 0; destination near last stop (~n_stops * 0.01 deg ≈ 1km+).
    stops = []
    for i in range(n_stops):
        stops.append(
            {
                "id": f"S{i}",
                "name": f"Stop {i}",
                "latitude": 12.85 + i * 0.005,
                "longitude": 77.66,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "provenance": p,
            }
        )
    return {
        "stops": stops,
        "stations": [],
        "routes": [
            {
                "id": "RLONG",
                "name": "Long Corridor",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "short_name": "L",
                "stop_ids": [f"S{i}" for i in range(n_stops)],
                "provenance": p,
            }
        ],
        "fare_rules": [],
    }


@pytest.fixture
def long_repo(tmp_path: Path) -> FileStaticMobilityRepository:
    repo = FileStaticMobilityRepository(tmp_path)
    _publish(repo, "bmtc", _long_bus_payload(25))
    return repo


class TestPhase6BGoalDirectedSearch:
    def test_long_corridor_discovered_without_huge_node_limit(self, long_repo):
        """Per-hop BFS would need ~25 legs; route continuation finds it under max_legs=8."""
        builder = DynamicJourneyBuilder(long_repo)
        # Origin near S0, dest near S24
        result = builder.build(
            _req(
                12.85,
                77.66,
                12.85 + 24 * 0.005,
                77.66,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    allow_road_access=False,
                    max_legs=8,
                    max_nodes_explored=500,  # deliberately modest
                    max_candidates=10,
                ),
            )
        )
        assert result.candidates, "expected at least one candidate on long corridor"
        assert "MAX_NODES_EXPLORED" not in result.warnings
        assert result.search_metadata["algorithm"] == _ALGORITHM
        assert result.search_metadata["nodes_explored"] <= 500
        bus = [c for c in result.candidates if "bus" in c.modes]
        assert bus
        assert any(
            any(leg.route_id == "RLONG" for leg in c.legs) for c in bus
        )

    def test_search_terminates_within_bounds(self, long_repo):
        builder = DynamicJourneyBuilder(long_repo)
        result = builder.build(
            _req(
                12.85,
                77.66,
                12.85 + 24 * 0.005,
                77.66,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    allow_road_access=False,
                    max_nodes_explored=50,
                    max_candidates=5,
                ),
            )
        )
        assert result.search_metadata["nodes_explored"] <= 51  # off-by-one at cap check
        assert result.search_metadata["search_termination_reason"] in {
            "exhausted",
            "candidate_cap",
            "max_nodes_explored",
        }

    def test_heuristic_missing_coords_is_zero(self):
        from src.journey_builder.builder import _heuristic_m
        from src.journey_builder.graph import MobilityNetworkGraph
        from src.journey_builder.models import GraphNode

        g = MobilityNetworkGraph()
        g.add_node(
            GraphNode(
                id="n1",
                kind=NodeKind.BUS_STOP,
                name="NoCoords",
                latitude=None,
                longitude=None,
            )
        )
        assert _heuristic_m(g, "n1", 12.0, 77.0) == 0.0

    def test_goal_directed_prefers_progress(self, tmp_path: Path):
        """Alighting filter keeps destination-egress and progress stops."""
        p = _prov()
        repo = FileStaticMobilityRepository(tmp_path)
        _publish(
            repo,
            "bmtc",
            {
                "stops": [
                    {
                        "id": "A",
                        "name": "A",
                        "latitude": 12.0,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                    {
                        "id": "B",
                        "name": "B",
                        "latitude": 12.05,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                    {
                        "id": "C",
                        "name": "C",
                        "latitude": 12.10,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                ],
                "stations": [],
                "routes": [
                    {
                        "id": "R",
                        "name": "R",
                        "provider": "BMTC",
                        "network": "bmtc",
                        "mode": "bus",
                        "stop_ids": ["A", "B", "C"],
                        "provenance": p,
                    }
                ],
                "fare_rules": [],
            },
        )
        builder = DynamicJourneyBuilder(repo)
        result = builder.build(
            _req(
                12.0,
                77.0,
                12.10,
                77.0,
                search_limits=SearchLimits(
                    max_walking_access_meters=300,
                    max_walking_egress_meters=300,
                    allow_road_access=False,
                ),
            )
        )
        assert result.candidates
        assert result.search_metadata["heuristic"] == "haversine_to_destination"

    def test_access_counts_bounded_by_radius(self, long_repo):
        builder = DynamicJourneyBuilder(long_repo)
        result = builder.build(
            _req(
                12.85,
                77.66,
                12.85 + 24 * 0.005,
                77.66,
                search_limits=SearchLimits(
                    max_walking_access_meters=150,
                    max_walking_egress_meters=150,
                    allow_road_access=False,
                ),
            )
        )
        # Only corridor ends should be within 150m of OD anchors.
        assert result.search_metadata["origin_access_count"] >= 1
        assert result.search_metadata["origin_access_count"] <= 3
        assert result.search_metadata["destination_access_count"] >= 1
        assert result.search_metadata["destination_access_count"] <= 3

    def test_walking_edges_do_not_all_pairs(self, long_repo):
        g = build_mobility_graph(long_repo, walk_transfer_meters=400)
        walk_edges = [
            e for e in g.edges.values() if e.kind == EdgeKind.TRANSFER_WALK
        ]
        # No BMRCL stations → no stop↔metro walk edges; bus-bus walks not generated.
        assert walk_edges == []
        assert len(g.edges) < len(g.nodes) * len(g.nodes)  # not all-pairs

    def test_different_routes_not_incorrectly_dominated(self, tmp_path: Path):
        p = _prov()
        repo = FileStaticMobilityRepository(tmp_path)
        _publish(
            repo,
            "bmtc",
            {
                "stops": [
                    {
                        "id": "O",
                        "name": "O",
                        "latitude": 12.0,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                    {
                        "id": "M",
                        "name": "M",
                        "latitude": 12.01,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                    {
                        "id": "D",
                        "name": "D",
                        "latitude": 12.02,
                        "longitude": 77.0,
                        "provider": "BMTC",
                        "network": "bmtc",
                        "stop_type": "bus_stop",
                        "provenance": p,
                    },
                ],
                "stations": [],
                "routes": [
                    {
                        "id": "R1",
                        "name": "R1",
                        "provider": "BMTC",
                        "network": "bmtc",
                        "mode": "bus",
                        "stop_ids": ["O", "D"],
                        "provenance": p,
                    },
                    {
                        "id": "R2",
                        "name": "R2",
                        "provider": "BMTC",
                        "network": "bmtc",
                        "mode": "bus",
                        "stop_ids": ["O", "M", "D"],
                        "provenance": p,
                    },
                ],
                "fare_rules": [],
            },
        )
        builder = DynamicJourneyBuilder(repo)
        result = builder.build(
            _req(
                12.0,
                77.0,
                12.02,
                77.0,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    allow_road_access=False,
                    max_candidates=20,
                ),
            )
        )
        route_sets = [
            {leg.route_id for leg in c.legs if leg.route_id} for c in result.candidates
        ]
        assert any("R1" in s for s in route_sets)
        assert any("R2" in s for s in route_sets)

    def test_excluded_modes_respected(self, long_repo):
        builder = DynamicJourneyBuilder(long_repo)
        result = builder.build(
            _req(
                12.85,
                77.66,
                12.85 + 24 * 0.005,
                77.66,
                constraints=JourneyConstraints(excluded_modes=["bus"]),
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    max_direct_walk_meters=50000,
                    allow_road_access=False,
                ),
            )
        )
        assert all("bus" not in c.modes for c in result.candidates)

    def test_no_journey_templates(self):
        assert_no_hardcoded_journeys(vars(builder_mod))
        assert not hasattr(builder_mod, "ROUTE_1065")
        assert "1065" not in Path(builder_mod.__file__).read_text(encoding="utf-8")

    def test_search_metadata_populated(self, long_repo):
        builder = DynamicJourneyBuilder(long_repo)
        result = builder.build(
            _req(12.85, 77.66, 12.85 + 24 * 0.005, 77.66)
        )
        meta = result.search_metadata
        for key in (
            "nodes_explored",
            "edges_considered",
            "candidates_generated",
            "candidates_pruned",
            "search_termination_reason",
            "max_depth_reached",
            "origin_access_nodes",
            "destination_access_nodes",
            "algorithm",
        ):
            assert key in meta
        assert meta["algorithm"] == _ALGORITHM

    def test_deterministic_identical_input(self, long_repo):
        builder = DynamicJourneyBuilder(long_repo)
        req = _req(12.85, 77.66, 12.85 + 24 * 0.005, 77.66)
        a = builder.build(req)
        b = builder.build(req)
        assert [c.candidate_id for c in a.candidates] == [
            c.candidate_id for c in b.candidates
        ]
        assert a.search_metadata["nodes_explored"] == b.search_metadata["nodes_explored"]


class TestPhase6BRealBmtcIntegration:
    @pytest.fixture(scope="class")
    def bmtc_repo(self) -> FileStaticMobilityRepository:
        repo = FileStaticMobilityRepository(MOBILITY_ROOT)
        snap = repo.get_active_snapshot("bmtc")
        if snap is None:
            pytest.skip(
                "Published BMTC snapshot not available locally "
                "(run scripts/phase6a_bmtc_audit.py first)"
            )
        # Sanity: real-scale feed, not the tiny fixture
        if len(snap.payload.get("stops") or []) < 1000:
            pytest.skip("Active BMTC snapshot looks like a tiny fixture, not Phase 6A feed")
        return repo

    def test_electronic_city_to_majestic_finds_candidate(self, bmtc_repo):
        builder = DynamicJourneyBuilder(bmtc_repo)
        limits = SearchLimits(
            max_walking_access_meters=800,
            max_walking_egress_meters=800,
            allow_road_access=False,
            max_nodes_explored=5000,
            max_candidates=20,
        )
        req = JourneyBuildRequest(
            origin_lat=ELECTRONIC_CITY.latitude,
            origin_lon=ELECTRONIC_CITY.longitude,
            destination_lat=MAJESTIC.latitude,
            destination_lon=MAJESTIC.longitude,
            departure_time=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            search_limits=limits,
        )
        t0 = time.perf_counter()
        result = builder.build(req)
        elapsed = time.perf_counter() - t0

        assert result.candidates, (
            f"expected ≥1 candidate; warnings={result.warnings} meta={result.search_metadata}"
        )
        assert "MAX_NODES_EXPLORED" not in result.warnings
        assert result.search_metadata["nodes_explored"] <= limits.max_nodes_explored
        assert result.search_metadata["algorithm"] == _ALGORITHM
        assert result.search_metadata["search_termination_reason"] in {
            "candidate_cap",
            "exhausted",
        }

        graph = build_mobility_graph(bmtc_repo)
        node_ids = set(graph.nodes)
        for c in result.candidates:
            assert c.temporal_feasibility in {"known", "unknown"}
            for leg in c.legs:
                if leg.from_node_id.startswith("access:"):
                    continue
                if leg.to_node_id.startswith("access:"):
                    continue
                assert leg.from_node_id in node_ids or leg.from_node_id.startswith(
                    "access:"
                )
                # Path references real graph endpoints for transit
                if leg.route_id:
                    assert leg.edge_kind in {EdgeKind.BUS, EdgeKind.METRO}
                    assert any(
                        e.route_id == leg.route_id for e in graph.edges.values()
                    )

        # Must not hardcode expectation on route 1065; only validate graph consistency.
        assert elapsed < 60.0  # soft local-dev bound
