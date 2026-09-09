"""
Phase 7K-6 — Authoritative BMRCL token fare integration.

Uses official station-count slabs (Revised Fare Chart 14.02.2025).
Does not hardcode production OD pairs into the fare algorithm.
"""

from __future__ import annotations

from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, preference_profile
from src.journey_builder.economics import (
    aggregate_journey_economics,
    annotate_leg_economics,
    reconcile_bmrcl_journey_fares,
)
from src.journey_builder.models import (
    EdgeKind,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
)
from src.network.models import MobilityMode
from src.network.transit_fares import (
    fare_for_stations_travelled,
    load_default_bmrcl_token_fare_rules,
    lookup_transit_fare_inr,
    select_bmrcl_token_fare_rule,
)


def _metro_leg(
    *,
    index: int,
    from_ref: str,
    to_ref: str,
    stations_travelled: int | None,
    route_id: str = "purple",
    provider: str = "BMRCL",
) -> JourneyLeg:
    meta = {}
    if stations_travelled is not None:
        meta["stations_travelled"] = stations_travelled
    leg = JourneyLeg(
        index=index,
        mode=MobilityMode.METRO,
        from_node_id=f"station:{from_ref}",
        to_node_id=f"station:{to_ref}",
        edge_id=f"m{index}",
        edge_kind=EdgeKind.METRO,
        from_ref=from_ref,
        to_ref=to_ref,
        route_id=route_id,
        provider=provider,
        distance_meters=1000.0 * (stations_travelled or 1),
        segment_role=SegmentRole.TRANSIT,
        metadata=meta,
    )
    return annotate_leg_economics(leg)


class TestPhase7K6BmrclFares:
    def test_authoritative_artifact_loads(self):
        rules = load_default_bmrcl_token_fare_rules()
        assert len(rules) >= 1
        rule = select_bmrcl_token_fare_rule(list(rules))
        assert rule is not None
        assert rule["id"] == "bmrcl_token_station_slabs_v20250214"
        assert rule["provenance"]["source_url"].endswith(
            "Revised_Fare_Chart_for_webiste.pdf"
        )
        assert rule["effective_from"].startswith("2025-02-14")

    def test_slab_boundaries(self):
        cases = [
            (0, 10),
            (1, 10),
            (2, 10),
            (3, 20),
            (4, 20),
            (5, 30),
            (6, 30),
            (7, 40),
            (8, 40),
            (9, 50),
            (10, 50),
            (11, 60),
            (15, 60),
            (16, 70),
            (20, 70),
            (21, 80),
            (25, 80),
            (26, 90),
            (30, 90),
            (31, 90),
            (40, 90),
        ]
        for stations, expected in cases:
            amount, status, meta = fare_for_stations_travelled(stations)
            assert status == ValueStatus.KNOWN.value, stations
            assert amount == expected, (stations, amount, expected)
            assert meta["fare_kind"] == "bmrcl_token_station_count_slabs"

    def test_lookup_with_stations_travelled(self):
        amount, status, meta = lookup_transit_fare_inr(
            mode=MobilityMode.METRO,
            from_station_id="nadaprabhu_kempegowda",
            to_station_id="mg_road",
            route_id="purple",
            stations_travelled=4,
        )
        assert amount == 20.0
        assert status == ValueStatus.KNOWN.value
        assert meta["provenance_source_url"].endswith(
            "Revised_Fare_Chart_for_webiste.pdf"
        )

    def test_unmatched_same_ids_same_station_fare(self):
        amount, status, _ = lookup_transit_fare_inr(
            mode=MobilityMode.METRO,
            from_station_id="mg_road",
            to_station_id="mg_road",
            stations_travelled=99,  # overridden by same-id rule
        )
        assert amount == 10.0
        assert status == ValueStatus.KNOWN.value

    def test_missing_stations_travelled_unknown(self):
        amount, status, meta = lookup_transit_fare_inr(
            mode=MobilityMode.METRO,
            from_station_id="a",
            to_station_id="b",
            stations_travelled=None,
        )
        assert amount is None
        assert status == ValueStatus.UNKNOWN.value
        assert amount != 0

    def test_bus_remains_unknown(self):
        amount, status, _ = lookup_transit_fare_inr(
            mode=MobilityMode.BUS,
            from_station_id="s1",
            to_station_id="s2",
            stations_travelled=3,
        )
        assert amount is None
        assert status == ValueStatus.UNKNOWN.value

    def test_transfer_span_single_fare_no_double_count(self):
        legs = [
            _metro_leg(
                index=0,
                from_ref="indiranagar",
                to_ref="nadaprabhu_kempegowda",
                stations_travelled=7,
                route_id="purple",
            ),
            JourneyLeg(
                index=1,
                mode=MobilityMode.WALK,
                from_node_id="station:nadaprabhu_kempegowda",
                to_node_id="station:nadaprabhu_kempegowda",
                edge_id="ix",
                edge_kind=EdgeKind.INTERCHANGE,
                distance_meters=0.0,
                is_transfer=True,
                segment_role=SegmentRole.TRANSFER,
                cost_inr=0.0,
                cost_status=ValueStatus.KNOWN.value,
                metadata={"interchange": True},
            ),
            _metro_leg(
                index=2,
                from_ref="nadaprabhu_kempegowda",
                to_ref="jayanagar",
                stations_travelled=6,
                route_id="green",
            ),
        ]
        # Per-leg annotate would be 40 + 30 if summed; span is 13 stations → 60.
        reconciled = reconcile_bmrcl_journey_fares(legs)
        assert reconciled[0].cost_inr == 60.0
        assert reconciled[0].cost_status == ValueStatus.KNOWN.value
        assert reconciled[2].cost_inr == 0.0
        assert reconciled[2].cost_status == ValueStatus.KNOWN.value
        assert (
            reconciled[2].metadata["cost_meta"]["fare_kind"]
            == "bmrcl_fare_included_in_prior_metro_leg"
        )
        agg = aggregate_journey_economics(reconciled)
        assert agg["total_cost_inr"] == 60.0
        assert agg["cost_status"] == ValueStatus.KNOWN.value

    def test_mixed_known_unknown_keeps_journey_unknown(self):
        legs = [
            annotate_leg_economics(
                JourneyLeg(
                    index=0,
                    mode=MobilityMode.WALK,
                    from_node_id="access:origin",
                    to_node_id="station:a",
                    edge_id="w0",
                    edge_kind=EdgeKind.WALK,
                    distance_meters=100.0,
                    segment_role=SegmentRole.ACCESS,
                )
            ),
            _metro_leg(
                index=1,
                from_ref="a",
                to_ref="b",
                stations_travelled=4,
            ),
            JourneyLeg(
                index=2,
                mode=MobilityMode.CAB,
                from_node_id="station:b",
                to_node_id="access:destination",
                edge_id="c2",
                edge_kind=EdgeKind.ROAD_ACCESS,
                distance_meters=2000.0,
                segment_role=SegmentRole.EGRESS,
                needs_enrichment=True,
                cost_inr=None,
                cost_status=ValueStatus.UNKNOWN.value,
            ),
        ]
        legs = reconcile_bmrcl_journey_fares(legs)
        assert legs[1].cost_status == ValueStatus.KNOWN.value
        agg = aggregate_journey_economics(legs)
        assert agg["cost_status"] == ValueStatus.UNKNOWN.value
        assert agg["total_cost_inr"] is None
        assert agg["partial_known_cost_sum_inr"] == 20.0

    def test_route_candidate_and_cheapest_with_metro_fare(self):
        metro = RouteCandidate(
            route_id="metro1",
            mode="metro",
            travel_time_minutes=15.0,
            cost=20.0,
            walking_minutes=5.0,
            transfers=0,
            congestion_score=0.2,
            reliability_score=0.8,
            disruption_risk=0.1,
            component_modes=["walk", "metro", "walk"],
            mode_signature="walk → metro → walk",
            cost_status="known",
            duration_status="unknown",
            walking_distance_meters=400.0,
        )
        auto = RouteCandidate(
            route_id="auto1",
            mode="auto",
            travel_time_minutes=25.0,
            cost=80.0,
            walking_minutes=1.0,
            transfers=0,
            congestion_score=0.4,
            reliability_score=0.7,
            disruption_risk=0.2,
            component_modes=["auto"],
            mode_signature="auto",
            cost_status="known",
            duration_status="known",
            walking_distance_meters=50.0,
        )
        cab_unknown = RouteCandidate(
            route_id="cab1",
            mode="cab",
            travel_time_minutes=20.0,
            cost=0.0,
            walking_minutes=0.0,
            transfers=0,
            congestion_score=0.3,
            reliability_score=0.7,
            disruption_risk=0.2,
            component_modes=["cab"],
            mode_signature="cab",
            cost_status="unknown",
            duration_status="known",
        )
        result = evaluate_routes(
            [metro, auto, cab_unknown],
            preference_profile("CHEAPEST"),
        )
        categories = {c.category: c.route.route_id for c in result.route_categories}
        assert categories.get("CHEAPEST") == "metro1"
        # Unknown-cost cab must not win CHEAPEST via fabricated ₹0.
        assert categories.get("CHEAPEST") != "cab1"
