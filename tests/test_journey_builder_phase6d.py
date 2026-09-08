"""
Phase 6D — first/last-mile + full-journey road connectivity (deterministic).

No hardcoded journey templates: candidates emerge from graph edges + search.
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
from src.journey_builder.economics import (
    aggregate_journey_economics,
    annotate_leg_economics,
    infer_segment_role,
    mode_signature,
)
from src.journey_builder.models import (
    EdgeKind,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
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
                max_walking_access_meters=800,
                max_walking_egress_meters=800,
                max_direct_walk_meters=2000,
                max_road_access_meters=5000,
                allow_road_access=True,
                allow_direct_road=True,
                max_transfers=3,
                max_legs=8,
                max_candidates=20,
                max_nodes_explored=5000,
            ),
        ),
    )


def _metro_corridor_payload():
    """Origin near M0; destination near M2 — walk/auto/cab access+egress possible."""
    p = _prov()
    stations = [
        {
            "id": "M0",
            "name": "Metro 0",
            "latitude": 12.9000,
            "longitude": 77.6000,
            "provider": "BMRCL",
            "lines": ["purple"],
            "line_order": {"purple": 0},
            "interchange_station_ids": [],
            "accessibility": {},
            "source_metadata": {},
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
            "accessibility": {},
            "source_metadata": {},
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
            "accessibility": {},
            "source_metadata": {},
            "provenance": p,
        },
    ]
    return {
        "stops": [],
        "stations": stations,
        "routes": [
            {
                "id": "purple",
                "name": "Purple",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "short_name": "P",
                "stop_ids": ["M0", "M1", "M2"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            }
        ],
        "fare_rules": [],
    }


@pytest.fixture
def metro_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish(repo, "bmrcl", _metro_corridor_payload())
    _publish(
        repo,
        "bmtc",
        {"stops": [], "stations": [], "routes": [], "interchanges": [], "fares": [], "stats": {}},
    )
    return repo


class TestPhase6DWalkOnly:
    def test_a_walk_only_od(self, metro_repo):
        # ~200m apart — within max_direct_walk
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(12.9000, 77.6000, 12.9015, 77.6000)
        )
        walk_only = [
            c
            for c in result.candidates
            if c.modes == ["walk"]
            and len(c.legs) == 1
            and c.legs[0].segment_role == SegmentRole.FULL_JOURNEY_ROAD
        ]
        assert walk_only
        j = walk_only[0]
        assert j.cost_status == ValueStatus.KNOWN.value
        assert j.total_cost_inr == 0.0
        assert j.duration_status == ValueStatus.KNOWN.value
        assert j.provenance_sources


class TestPhase6DTransitWalking:
    def test_b_walk_transit_walk(self, metro_repo):
        # Origin ~100m south of M0; dest ~100m north of M2
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.8992,
                77.6000,
                12.9208,
                77.6000,
                search_limits=SearchLimits(
                    max_walking_access_meters=800,
                    max_walking_egress_meters=800,
                    allow_road_access=False,
                    allow_direct_road=False,
                    max_candidates=20,
                    max_nodes_explored=5000,
                ),
            )
        )
        sigs = {c.mode_signature for c in result.candidates}
        assert any("walk → metro → walk" == s for s in sigs)
        j = next(c for c in result.candidates if c.mode_signature == "walk → metro → walk")
        assert j.legs[0].segment_role == SegmentRole.ACCESS
        assert j.legs[1].segment_role == SegmentRole.TRANSIT
        assert j.legs[2].segment_role == SegmentRole.EGRESS
        assert j.access_walking_meters > 0
        assert j.egress_walking_meters > 0


class TestPhase6DAutoCabAccessEgress:
    def test_c_walk_metro_auto(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.8992,
                77.6000,
                12.9250,
                77.6000,  # beyond walk egress, within road egress
                search_limits=SearchLimits(
                    max_walking_access_meters=800,
                    max_walking_egress_meters=200,  # force road egress
                    max_road_access_meters=5000,
                    allow_road_access=True,
                    allow_direct_road=False,
                    max_candidates=100,
                    max_nodes_explored=5000,
                ),
            )
        )
        assert any(
            c.mode_signature == "walk → metro → auto" for c in result.candidates
        ), {c.mode_signature for c in result.candidates}

    def test_d_auto_metro_walk(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.8950,
                77.6000,  # beyond walk access
                12.9208,
                77.6000,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=800,
                    max_road_access_meters=5000,
                    allow_road_access=True,
                    allow_direct_road=False,
                    max_candidates=100,
                    max_nodes_explored=5000,
                ),
            )
        )
        assert any(
            c.mode_signature == "auto → metro → walk" for c in result.candidates
        ), {c.mode_signature for c in result.candidates}


class TestPhase6DFullJourneyRoad:
    def test_e_auto_only(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        # Far enough that walk-only is off; road direct on
        result = builder.build(
            _req(
                12.90,
                77.60,
                12.95,
                77.65,
                search_limits=SearchLimits(
                    max_direct_walk_meters=500,
                    allow_road_access=True,
                    allow_direct_road=True,
                    max_candidates=20,
                    max_nodes_explored=3000,
                ),
            )
        )
        autos = [
            c
            for c in result.candidates
            if c.modes == ["auto_rickshaw"]
            and c.legs[0].segment_role == SegmentRole.FULL_JOURNEY_ROAD
        ]
        assert autos
        j = autos[0]
        assert j.cost_status == ValueStatus.KNOWN.value
        assert j.total_cost_inr is not None and j.total_cost_inr > 0
        assert j.legs[0].metadata.get("cost_meta", {}).get("fare_kind") == (
            "government_regulated_estimate"
        )
        assert j.legs[0].needs_enrichment is True

    def test_f_cab_only(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.90,
                77.60,
                12.95,
                77.65,
                search_limits=SearchLimits(
                    max_direct_walk_meters=500,
                    allow_road_access=True,
                    allow_direct_road=True,
                    max_candidates=20,
                    max_nodes_explored=3000,
                ),
            )
        )
        cabs = [
            c
            for c in result.candidates
            if c.modes == ["cab"]
            and c.legs[0].segment_role == SegmentRole.FULL_JOURNEY_ROAD
        ]
        assert cabs
        j = cabs[0]
        assert j.cost_status == ValueStatus.UNKNOWN.value
        assert j.total_cost_inr is None
        assert j.legs[0].metadata.get("cost_meta", {}).get("fare_kind") == (
            "cab_fare_not_configured"
        )


class TestPhase6DCabExclusion:
    def test_g_excluded_cab_keeps_auto(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        limits = SearchLimits(
            max_direct_walk_meters=500,
            allow_road_access=True,
            allow_direct_road=True,
            max_candidates=20,
            max_nodes_explored=3000,
        )
        with_cab = builder.build(
            _req(12.90, 77.60, 12.95, 77.65, search_limits=limits)
        )
        assert any("cab" in c.modes for c in with_cab.candidates)

        no_cab = builder.build(
            _req(
                12.90,
                77.60,
                12.95,
                77.65,
                constraints=JourneyConstraints(excluded_modes=["cab"]),
                search_limits=limits,
            )
        )
        for c in no_cab.candidates:
            assert "cab" not in c.modes
        assert any("auto_rickshaw" in c.modes for c in no_cab.candidates)

        # Multimodal cab access also gone
        multi = builder.build(
            _req(
                12.8950,
                77.6000,
                12.9208,
                77.6000,
                constraints=JourneyConstraints(excluded_modes=["cab"]),
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=800,
                    allow_road_access=True,
                    allow_direct_road=False,
                    max_candidates=30,
                    max_nodes_explored=5000,
                ),
            )
        )
        for c in multi.candidates:
            assert "cab" not in c.modes


class TestPhase6DAggregation:
    def test_h_cost_aggregation_multi_segment(self):
        legs = [
            JourneyLeg(
                index=0,
                mode=MobilityMode.WALK,
                from_node_id="access:origin",
                to_node_id="n1",
                edge_id="e0",
                edge_kind=EdgeKind.WALK,
                distance_meters=100,
                segment_role=SegmentRole.ACCESS,
            ),
            JourneyLeg(
                index=1,
                mode=MobilityMode.AUTO_RICKSHAW,
                from_node_id="n1",
                to_node_id="access:destination",
                edge_id="e1",
                edge_kind=EdgeKind.ROAD_ACCESS,
                distance_meters=2000,
                segment_role=SegmentRole.EGRESS,
            ),
        ]
        legs = [annotate_leg_economics(l) for l in legs]
        econ = aggregate_journey_economics(legs)
        # Walk known + auto known → total known
        assert legs[0].cost_inr == 0.0
        assert legs[1].cost_inr is not None and legs[1].cost_inr > 0
        assert econ["cost_status"] == ValueStatus.KNOWN.value
        assert econ["total_cost_inr"] == pytest.approx(
            legs[0].cost_inr + legs[1].cost_inr
        )

        # Cab makes journey cost unknown
        cab = annotate_leg_economics(
            JourneyLeg(
                index=2,
                mode=MobilityMode.CAB,
                from_node_id="a",
                to_node_id="b",
                edge_id="e2",
                edge_kind=EdgeKind.ROAD_DIRECT,
                distance_meters=5000,
                segment_role=SegmentRole.FULL_JOURNEY_ROAD,
                needs_enrichment=True,
            )
        )
        econ2 = aggregate_journey_economics([legs[0], cab])
        assert econ2["cost_status"] == ValueStatus.UNKNOWN.value
        assert econ2["total_cost_inr"] is None

    def test_i_duration_aggregation(self):
        walk = annotate_leg_economics(
            JourneyLeg(
                index=0,
                mode=MobilityMode.WALK,
                from_node_id="access:origin",
                to_node_id="access:destination",
                edge_id="e0",
                edge_kind=EdgeKind.WALK,
                distance_meters=240,  # 3 min at 80m/min
                segment_role=SegmentRole.FULL_JOURNEY_ROAD,
            )
        )
        econ = aggregate_journey_economics([walk])
        assert econ["duration_status"] == ValueStatus.KNOWN.value
        assert econ["total_duration_seconds"] == pytest.approx(180.0)

        road = annotate_leg_economics(
            JourneyLeg(
                index=0,
                mode=MobilityMode.CAB,
                from_node_id="access:origin",
                to_node_id="access:destination",
                edge_id="e0",
                edge_kind=EdgeKind.ROAD_DIRECT,
                distance_meters=5000,
                needs_enrichment=True,
                segment_role=SegmentRole.FULL_JOURNEY_ROAD,
            )
        )
        econ_r = aggregate_journey_economics([road])
        assert econ_r["duration_status"] == ValueStatus.UNKNOWN.value

    def test_j_walking_breakdown(self):
        legs = [
            annotate_leg_economics(
                JourneyLeg(
                    index=0,
                    mode=MobilityMode.WALK,
                    from_node_id="access:origin",
                    to_node_id="s1",
                    edge_id="e0",
                    edge_kind=EdgeKind.WALK,
                    distance_meters=100,
                    segment_role=SegmentRole.ACCESS,
                )
            ),
            annotate_leg_economics(
                JourneyLeg(
                    index=1,
                    mode=MobilityMode.WALK,
                    from_node_id="s1",
                    to_node_id="s2",
                    edge_id="e1",
                    edge_kind=EdgeKind.TRANSFER_WALK,
                    distance_meters=50,
                    segment_role=SegmentRole.TRANSFER,
                )
            ),
            annotate_leg_economics(
                JourneyLeg(
                    index=2,
                    mode=MobilityMode.WALK,
                    from_node_id="s2",
                    to_node_id="access:destination",
                    edge_id="e2",
                    edge_kind=EdgeKind.WALK,
                    distance_meters=200,
                    segment_role=SegmentRole.EGRESS,
                )
            ),
        ]
        econ = aggregate_journey_economics(legs)
        assert econ["access_walking_meters"] == 100
        assert econ["transfer_walking_meters"] == 50
        assert econ["egress_walking_meters"] == 200
        assert econ["walking_distance_meters"] == 350


class TestPhase6DProvenanceAndRoles:
    def test_k_provenance_survives_aggregation(self, metro_repo):
        builder = DynamicJourneyBuilder(metro_repo)
        result = builder.build(
            _req(
                12.90,
                77.60,
                12.95,
                77.65,
                search_limits=SearchLimits(
                    max_direct_walk_meters=500,
                    allow_road_access=True,
                    allow_direct_road=True,
                    max_candidates=10,
                    max_nodes_explored=2000,
                ),
            )
        )
        for c in result.candidates:
            assert c.provenance_sources
            for leg in c.legs:
                assert leg.provenance is not None
                assert leg.provenance.source

    def test_role_inference_and_signature(self):
        assert (
            infer_segment_role(
                EdgeKind.ROAD_DIRECT,
                from_node_id="access:origin",
                to_node_id="access:destination",
                is_first=True,
                is_last=True,
                is_only=True,
            )
            == SegmentRole.FULL_JOURNEY_ROAD
        )
        legs = [
            JourneyLeg(
                index=0,
                mode=MobilityMode.AUTO_RICKSHAW,
                from_node_id="a",
                to_node_id="b",
                edge_id="e0",
                edge_kind=EdgeKind.ROAD_ACCESS,
                segment_role=SegmentRole.ACCESS,
            ),
            JourneyLeg(
                index=1,
                mode=MobilityMode.METRO,
                from_node_id="b",
                to_node_id="c",
                edge_id="e1",
                edge_kind=EdgeKind.METRO,
                segment_role=SegmentRole.TRANSIT,
            ),
            JourneyLeg(
                index=2,
                mode=MobilityMode.WALK,
                from_node_id="c",
                to_node_id="d",
                edge_id="e2",
                edge_kind=EdgeKind.WALK,
                segment_role=SegmentRole.EGRESS,
            ),
        ]
        assert mode_signature(legs) == "auto → metro → walk"

    def test_no_hardcoded_journey_templates(self):
        import src.journey_builder as jb_pkg
        import src.journey_builder.builder as builder_mod
        import src.journey_builder.economics as econ_mod

        assert_no_hardcoded_journeys(vars(jb_pkg))
        assert_no_hardcoded_journeys(vars(builder_mod))
        assert_no_hardcoded_journeys(vars(econ_mod))


class TestPhase6DDecisionEngineExclusion:
    def test_hybrid_cab_leg_excluded_via_component_modes(self):
        from src.decision_engine.models import RouteCandidate, UserPreferences
        from src.decision_engine.scoring import validate_hard_constraints

        cand = RouteCandidate(
            route_id="j1",
            mode="hybrid",
            travel_time_minutes=40,
            cost=0,
            walking_minutes=5,
            transfers=1,
            congestion_score=0.2,
            reliability_score=0.7,
            disruption_risk=0.1,
            component_modes=["cab", "metro", "walk"],
        )
        viol = validate_hard_constraints(
            cand, UserPreferences(excluded_modes=["cab"])
        )
        assert any("EXCLUDED_MODE" in v for v in viol)

        ok = RouteCandidate(
            route_id="j2",
            mode="hybrid",
            travel_time_minutes=40,
            cost=0,
            walking_minutes=5,
            transfers=1,
            congestion_score=0.2,
            reliability_score=0.7,
            disruption_risk=0.1,
            component_modes=["auto_rickshaw", "metro", "walk"],
        )
        assert validate_hard_constraints(
            ok, UserPreferences(excluded_modes=["cab"])
        ) == []
