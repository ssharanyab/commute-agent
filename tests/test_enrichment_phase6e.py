"""
Phase 6E — enrichment write-back, aggregation, unknown-cost Decision Engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from src.agent.capabilities import TrafficEnrichmentResult
from src.agent.capabilities.adapt import journeys_to_route_candidates
from src.agent.capabilities.enrichment_apply import (
    apply_traffic_enrichment_to_journey,
)
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import (
    PROFILE_CHEAPEST,
    PROFILE_FASTEST,
    RouteCandidate,
    UserPreferences,
    preference_profile,
)
from src.decision_engine.scoring import (
    normalize_candidate_pool,
    validate_hard_constraints,
)
from src.journey_builder.economics import annotate_leg_economics
from src.journey_builder.models import (
    EdgeKind,
    EnrichmentRequirement,
    Journey,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
)
from src.network.models import MobilityMode


def _leg(
    index: int,
    mode: MobilityMode,
    *,
    dist: float,
    role: SegmentRole,
    kind: EdgeKind,
    needs_enrichment: bool = False,
) -> JourneyLeg:
    leg = JourneyLeg(
        index=index,
        mode=mode,
        from_node_id=f"n{index}",
        to_node_id=f"n{index+1}",
        edge_id=f"e{index}",
        edge_kind=kind,
        distance_meters=dist,
        needs_enrichment=needs_enrichment,
        segment_role=role,
    )
    return annotate_leg_economics(leg)


def _journey(legs: List[JourneyLeg], *, cid: str = "j1") -> Journey:
    from src.journey_builder.economics import aggregate_journey_economics, mode_signature

    econ = aggregate_journey_economics(legs)
    modes = [l.mode.value for l in legs]
    reqs = []
    for leg in legs:
        if leg.needs_enrichment:
            reqs.append(
                EnrichmentRequirement(
                    requirement_type="road_geometry_time",
                    leg_index=leg.index,
                    mode=leg.mode.value,
                    from_lat=12.9,
                    from_lon=77.6,
                    to_lat=12.91,
                    to_lon=77.6,
                )
            )
    return Journey(
        candidate_id=cid,
        origin=(12.9, 77.6),
        destination=(12.92, 77.6),
        legs=legs,
        transfer_count=0,
        walking_distance_meters=econ["walking_distance_meters"],
        transit_leg_count=sum(1 for l in legs if l.mode.value in {"bus", "metro"}),
        road_leg_count=sum(
            1 for l in legs if l.edge_kind in {EdgeKind.ROAD_ACCESS, EdgeKind.ROAD_DIRECT}
        ),
        modes=modes,
        snapshot_versions={},
        provenance_sources=["test"],
        enrichment_requirements=reqs,
        total_cost_inr=econ["total_cost_inr"],
        cost_status=econ["cost_status"],
        total_duration_seconds=econ["total_duration_seconds"],
        duration_status=econ["duration_status"],
        access_walking_meters=econ["access_walking_meters"],
        transfer_walking_meters=econ["transfer_walking_meters"],
        egress_walking_meters=econ["egress_walking_meters"],
        mode_signature=mode_signature(legs),
    )


class TestSegmentEnrichmentWriteBack:
    def test_road_leg_receives_maps_duration_and_distance(self):
        legs = [
            _leg(
                0,
                MobilityMode.AUTO_RICKSHAW,
                dist=2000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        enr = [
            TrafficEnrichmentResult(
                journey_id="j1",
                leg_index=0,
                available=True,
                duration_minutes=12.0,
                distance_meters=2500.0,
                traffic_info={"congestion_score": 0.4},
                provenance={"source": "google_maps_routes"},
                reason="ok",
            )
        ]
        out = apply_traffic_enrichment_to_journey(j, enr)
        assert out.legs[0].duration_seconds == pytest.approx(720.0)
        assert out.legs[0].distance_meters == 2500.0
        assert out.legs[0].duration_status == ValueStatus.KNOWN.value
        assert out.duration_status == ValueStatus.KNOWN.value
        assert out.total_duration_seconds == pytest.approx(720.0)
        assert out.legs[0].provenance is not None
        assert out.legs[0].provenance.source == "google_maps_routes"

    def test_multiple_road_segments_enriched_independently(self):
        legs = [
            _leg(
                0,
                MobilityMode.CAB,
                dist=1000,
                role=SegmentRole.ACCESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
            _leg(
                1,
                MobilityMode.METRO,
                dist=5000,
                role=SegmentRole.TRANSIT,
                kind=EdgeKind.METRO,
            ),
            _leg(
                2,
                MobilityMode.AUTO_RICKSHAW,
                dist=1500,
                role=SegmentRole.EGRESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
        ]
        j = _journey(legs)
        enr = [
            TrafficEnrichmentResult(
                journey_id="j1",
                leg_index=0,
                available=True,
                duration_minutes=5.0,
                distance_meters=1100.0,
                provenance={"source": "google_maps_routes"},
                reason="ok",
            ),
            TrafficEnrichmentResult(
                journey_id="j1",
                leg_index=2,
                available=True,
                duration_minutes=8.0,
                distance_meters=1600.0,
                provenance={"source": "google_maps_routes"},
                reason="ok",
            ),
        ]
        out = apply_traffic_enrichment_to_journey(j, enr)
        assert out.legs[0].duration_seconds == pytest.approx(300.0)
        assert out.legs[2].duration_seconds == pytest.approx(480.0)
        assert out.legs[1].duration_status == ValueStatus.UNKNOWN.value  # metro structural
        # Journey duration unknown because metro unknown
        assert out.duration_status == ValueStatus.UNKNOWN.value

    def test_enrichment_failure_does_not_become_zero(self):
        legs = [
            _leg(
                0,
                MobilityMode.CAB,
                dist=5000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        enr = [
            TrafficEnrichmentResult(
                journey_id="j1",
                leg_index=0,
                available=False,
                reason="NO_ROUTES",
                provenance={"source": "google_maps_routes"},
            )
        ]
        out = apply_traffic_enrichment_to_journey(j, enr)
        assert out.legs[0].duration_seconds is None
        assert out.legs[0].duration_status == ValueStatus.UNAVAILABLE.value
        assert out.legs[0].distance_meters == 5000.0  # preserved, not zeroed


class TestUnknownCostSemantics:
    def test_cab_unknown_cost_not_zero_scoring(self):
        known = RouteCandidate(
            route_id="bus",
            mode="bus",
            travel_time_minutes=50,
            cost=40.0,
            walking_minutes=10,
            transfers=0,
            congestion_score=0.3,
            reliability_score=0.7,
            disruption_risk=0.1,
            cost_status="known",
        )
        cab = RouteCandidate(
            route_id="cab",
            mode="cab",
            travel_time_minutes=25,
            cost=0.0,  # placeholder
            walking_minutes=0,
            transfers=0,
            congestion_score=0.3,
            reliability_score=0.7,
            disruption_risk=0.1,
            cost_status="unknown",
        )
        norms = normalize_candidate_pool([known, cab])
        assert norms["cab"]["cost"] == 0.5  # neutral mid-scale
        assert norms["bus"]["cost"] == 0.0  # sole known → scale 0

        res = evaluate_routes([known, cab], preference_profile(PROFILE_CHEAPEST))
        # CHEAPEST among known costs → bus, not cab-as-free
        assert res.recommended_route.route_id == "bus"
        # Category CHEAPEST also from known pool
        cheapest_cat = next(
            (c for c in res.route_categories if c.category == "CHEAPEST"),
            None,
        )
        if cheapest_cat:
            assert cheapest_cat.route.route_id == "bus"

    def test_adapt_preserves_unknown_cab_cost_status(self):
        legs = [
            _leg(
                0,
                MobilityMode.CAB,
                dist=8000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        assert j.cost_status == ValueStatus.UNKNOWN.value
        cands = journeys_to_route_candidates([j])
        assert cands[0].cost_status == "unknown"
        assert cands[0].cost == 0.0  # placeholder only
        # Without enrichment, duration unknown — not invented as 15 min preferred
        assert cands[0].duration_status == "unknown"
        assert cands[0].travel_time_minutes == 0.0  # no known leg minutes

    def test_partial_cost_aggregation(self):
        legs = [
            _leg(
                0,
                MobilityMode.WALK,
                dist=200,
                role=SegmentRole.ACCESS,
                kind=EdgeKind.WALK,
            ),
            _leg(
                1,
                MobilityMode.AUTO_RICKSHAW,
                dist=3000,
                role=SegmentRole.EGRESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
        ]
        j = _journey(legs)
        assert j.cost_status == ValueStatus.KNOWN.value  # walk+auto both priced
        assert j.total_cost_inr is not None and j.total_cost_inr > 0

        legs2 = [
            legs[0],
            _leg(
                1,
                MobilityMode.CAB,
                dist=3000,
                role=SegmentRole.EGRESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
        ]
        j2 = _journey(legs2, cid="j2")
        assert j2.cost_status == ValueStatus.UNKNOWN.value
        assert j2.total_cost_inr is None
        cands = journeys_to_route_candidates([j2])
        assert cands[0].partial_known_cost_inr == 0.0  # walk zero


class TestWalkingAggregation:
    def test_access_transfer_egress_sum(self):
        legs = [
            _leg(0, MobilityMode.WALK, dist=100, role=SegmentRole.ACCESS, kind=EdgeKind.WALK),
            _leg(
                1,
                MobilityMode.WALK,
                dist=50,
                role=SegmentRole.TRANSFER,
                kind=EdgeKind.TRANSFER_WALK,
            ),
            _leg(2, MobilityMode.WALK, dist=200, role=SegmentRole.EGRESS, kind=EdgeKind.WALK),
        ]
        j = _journey(legs)
        assert j.access_walking_meters == 100
        assert j.transfer_walking_meters == 50
        assert j.egress_walking_meters == 200
        assert j.walking_distance_meters == 350


class TestHardConstraintsCompleteJourney:
    def test_cab_exclusion_on_hybrid_component_modes(self):
        cand = RouteCandidate(
            route_id="h",
            mode="hybrid",
            travel_time_minutes=40,
            cost=0,
            walking_minutes=5,
            transfers=1,
            congestion_score=0.2,
            reliability_score=0.7,
            disruption_risk=0.1,
            component_modes=["auto_rickshaw", "metro", "cab"],
            cost_status="unknown",
        )
        viol = validate_hard_constraints(
            cand, UserPreferences(excluded_modes=["cab"])
        )
        assert any("EXCLUDED_MODE" in v for v in viol)


class TestProfilesDeterministic:
    def test_fastest_prefers_shorter_time(self):
        a = RouteCandidate(
            "a", "cab", 20.0, 0.0, 0.0, 0, 0.3, 0.7, 0.1, cost_status="unknown"
        )
        b = RouteCandidate(
            "b", "bus", 45.0, 30.0, 8.0, 0, 0.3, 0.7, 0.1, cost_status="known"
        )
        res = evaluate_routes([a, b], preference_profile(PROFILE_FASTEST))
        assert res.recommended_route.route_id == "a"
