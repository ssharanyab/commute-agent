"""
Phase 7K-2 — Metro fare/duration status propagation (fixture-based).

Does not hardcode production OD pairs. Does not invent published BMRCL fares.
"""

from __future__ import annotations

from src.journey_builder.economics import (
    METRO_M_PER_S,
    aggregate_journey_economics,
    annotate_leg_economics,
)
from src.journey_builder.models import (
    EdgeKind,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
)
from src.network.models import MobilityMode
from src.network.transit_fares import lookup_transit_fare_inr


def _leg(
    *,
    mode: MobilityMode,
    dist: float | None,
    role: SegmentRole,
    index: int = 0,
    from_ref: str = "a",
    to_ref: str = "b",
    cost_inr=None,
    cost_status=None,
    duration_seconds=None,
    duration_status=None,
) -> JourneyLeg:
    base = JourneyLeg(
        index=index,
        mode=mode,
        from_node_id=f"n:{from_ref}",
        to_node_id=f"n:{to_ref}",
        edge_id=f"e{index}",
        edge_kind=EdgeKind.METRO if mode == MobilityMode.METRO else EdgeKind.WALK,
        from_ref=from_ref,
        to_ref=to_ref,
        distance_meters=dist,
        segment_role=role,
        cost_inr=cost_inr,
        cost_status=cost_status or ValueStatus.UNKNOWN.value,
        duration_seconds=duration_seconds,
        duration_status=duration_status or ValueStatus.UNKNOWN.value,
    )
    if cost_inr is not None or duration_seconds is not None:
        return base
    return annotate_leg_economics(base)


class TestPhase7K2MetroEconomics:
    def test_lookup_without_stations_travelled_is_unknown_not_zero(self):
        amount, status, meta = lookup_transit_fare_inr(
            mode=MobilityMode.METRO,
            from_station_id="near_o",
            to_station_id="near_d",
            fare_rules=[],
        )
        assert amount is None
        assert status == ValueStatus.UNKNOWN.value
        assert amount != 0
        assert meta["fare_kind"] == "bmrcl_stations_travelled_unknown"

    def test_walk_metro_walk_unknown_fare_aggregate(self):
        legs = [
            _leg(
                mode=MobilityMode.WALK,
                dist=200.0,
                role=SegmentRole.ACCESS,
                index=0,
            ),
            _leg(
                mode=MobilityMode.METRO,
                dist=3500.0,
                role=SegmentRole.TRANSIT,
                index=1,
                from_ref="near_o",
                to_ref="near_d",
            ),
            _leg(
                mode=MobilityMode.WALK,
                dist=300.0,
                role=SegmentRole.EGRESS,
                index=2,
            ),
        ]
        metro = legs[1]
        assert metro.cost_inr is None
        assert metro.cost_status == ValueStatus.UNKNOWN.value
        assert metro.cost_inr != 0
        assert metro.duration_seconds is not None
        assert metro.duration_seconds == 3500.0 / METRO_M_PER_S
        assert metro.duration_status == ValueStatus.UNKNOWN.value

        agg = aggregate_journey_economics(legs)
        assert agg["total_cost_inr"] is None
        assert agg["cost_status"] == ValueStatus.UNKNOWN.value
        assert agg["partial_known_cost_sum_inr"] == 0.0  # walk zero
        assert agg["total_duration_seconds"] is None  # metro duration unknown
        assert agg["duration_status"] == ValueStatus.UNKNOWN.value
        assert agg["walking_distance_meters"] == 500.0

    def test_known_metro_fare_and_duration_propagate(self):
        legs = [
            JourneyLeg(
                index=0,
                mode=MobilityMode.WALK,
                from_node_id="access:origin",
                to_node_id="station:a",
                edge_id="w0",
                edge_kind=EdgeKind.WALK,
                distance_meters=200.0,
                segment_role=SegmentRole.ACCESS,
                cost_inr=0.0,
                cost_status=ValueStatus.KNOWN.value,
                duration_seconds=150.0,
                duration_status=ValueStatus.KNOWN.value,
                walking_meters=200.0,
            ),
            JourneyLeg(
                index=1,
                mode=MobilityMode.METRO,
                from_node_id="station:a",
                to_node_id="station:b",
                edge_id="m1",
                edge_kind=EdgeKind.METRO,
                from_ref="a",
                to_ref="b",
                distance_meters=3500.0,
                segment_role=SegmentRole.TRANSIT,
                cost_inr=20.0,
                cost_status=ValueStatus.KNOWN.value,
                duration_seconds=420.0,
                duration_status=ValueStatus.KNOWN.value,
                walking_meters=0.0,
            ),
            JourneyLeg(
                index=2,
                mode=MobilityMode.WALK,
                from_node_id="station:b",
                to_node_id="access:destination",
                edge_id="w2",
                edge_kind=EdgeKind.WALK,
                distance_meters=300.0,
                segment_role=SegmentRole.EGRESS,
                cost_inr=0.0,
                cost_status=ValueStatus.KNOWN.value,
                duration_seconds=225.0,
                duration_status=ValueStatus.KNOWN.value,
                walking_meters=300.0,
            ),
        ]
        agg = aggregate_journey_economics(legs)
        assert agg["cost_status"] == ValueStatus.KNOWN.value
        assert agg["total_cost_inr"] == 20.0
        assert agg["duration_status"] == ValueStatus.KNOWN.value
        assert agg["total_duration_seconds"] == 795.0
        assert agg["walking_distance_meters"] == 500.0

    def test_unknown_metro_duration_keeps_journey_duration_unknown(self):
        legs = [
            _leg(mode=MobilityMode.WALK, dist=100.0, role=SegmentRole.ACCESS, index=0),
            JourneyLeg(
                index=1,
                mode=MobilityMode.METRO,
                from_node_id="station:a",
                to_node_id="station:b",
                edge_id="m1",
                edge_kind=EdgeKind.METRO,
                distance_meters=None,
                segment_role=SegmentRole.TRANSIT,
                cost_inr=None,
                cost_status=ValueStatus.UNKNOWN.value,
                duration_seconds=None,
                duration_status=ValueStatus.UNKNOWN.value,
            ),
            _leg(mode=MobilityMode.WALK, dist=100.0, role=SegmentRole.EGRESS, index=2),
        ]
        # Re-annotate walk legs only; metro stays unknown/empty.
        legs[0] = annotate_leg_economics(legs[0])
        legs[2] = annotate_leg_economics(legs[2])
        agg = aggregate_journey_economics(legs)
        assert agg["duration_status"] == ValueStatus.UNKNOWN.value
        assert agg["total_duration_seconds"] is None
        assert agg["cost_status"] == ValueStatus.UNKNOWN.value
        assert agg["total_cost_inr"] is None
