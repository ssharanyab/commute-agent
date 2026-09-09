"""
Phase 7K-9 — self-transfer / null-movement access-egress collapse.

Does not change Decision Engine weights, fares, or OD-specific rules.
"""

from __future__ import annotations

from src.journey_builder.models import (
    EdgeKind,
    Journey,
    JourneyLeg,
    SegmentRole,
)
from src.journey_builder.normalize import (
    collapse_null_movement_legs,
    is_null_movement_leg,
    normalize_journey_legs,
)
from src.journey_builder.steps import build_journey_steps
from src.network.models import MobilityMode


def _leg(
    *,
    index: int,
    mode: MobilityMode,
    from_id: str,
    to_id: str,
    from_ref: str | None = None,
    to_ref: str | None = None,
    from_name: str | None = None,
    to_name: str | None = None,
    distance_meters: float | None = 0.0,
    route_id: str | None = None,
    is_transfer: bool = False,
    edge_kind: EdgeKind | None = None,
    segment_role: SegmentRole = SegmentRole.OTHER,
) -> JourneyLeg:
    if edge_kind is None:
        if mode == MobilityMode.WALK:
            edge_kind = EdgeKind.WALK
        elif mode == MobilityMode.METRO:
            edge_kind = EdgeKind.METRO
        elif mode == MobilityMode.BUS:
            edge_kind = EdgeKind.BUS
        else:
            edge_kind = EdgeKind.ROAD_ACCESS
    return JourneyLeg(
        index=index,
        mode=mode,
        from_node_id=from_id,
        to_node_id=to_id,
        edge_id=f"e{index}",
        edge_kind=edge_kind,
        from_ref=from_ref,
        to_ref=to_ref,
        from_name=from_name,
        to_name=to_name,
        distance_meters=distance_meters,
        route_id=route_id,
        is_transfer=is_transfer,
        segment_role=segment_role,
        needs_enrichment=mode in {MobilityMode.AUTO_RICKSHAW, MobilityMode.CAB},
    )


def _journey(legs: list[JourneyLeg]) -> Journey:
    modes = [leg.mode.value for leg in legs]
    return Journey(
        candidate_id="j_self",
        origin=(12.97, 77.57),
        destination=(12.97, 77.64),
        legs=legs,
        transfer_count=sum(1 for l in legs if l.is_transfer),
        walking_distance_meters=0.0,
        transit_leg_count=sum(1 for l in legs if l.mode == MobilityMode.METRO),
        road_leg_count=sum(
            1 for l in legs if l.mode == MobilityMode.AUTO_RICKSHAW
        ),
        modes=modes,
        snapshot_versions={},
        provenance_sources=[],
        mode_signature=" → ".join(modes),
    )


class TestPhase7K9SelfTransferCollapse:
    def test_metro_walk_auto_drops_self_walk(self):
        """Screenshot pattern: Metro→Walk(X→X)→Auto — self-walk must go."""
        x = "station:indiranagar"
        legs = [
            _leg(
                index=0,
                mode=MobilityMode.METRO,
                from_id="station:majestic",
                to_id=x,
                from_ref="nadaprabhu_kempegowda",
                to_ref="indiranagar",
                from_name="Majestic",
                to_name="Indiranagar",
                distance_meters=5000.0,
                route_id="purple",
                segment_role=SegmentRole.TRANSIT,
            ),
            _leg(
                index=1,
                mode=MobilityMode.WALK,
                from_id=x,
                to_id=x,
                from_ref="indiranagar",
                to_ref="indiranagar",
                from_name="Indiranagar",
                to_name="Indiranagara Metro Station",
                distance_meters=0.0,
                segment_role=SegmentRole.EGRESS,
            ),
            _leg(
                index=2,
                mode=MobilityMode.AUTO_RICKSHAW,
                from_id=x,
                to_id="access:destination",
                from_ref="indiranagar",
                to_ref=None,
                from_name="Indiranagar",
                to_name="Metro Station Indira Nagar",
                distance_meters=1800.0,
                segment_role=SegmentRole.EGRESS,
                is_transfer=True,
            ),
        ]
        out = normalize_journey_legs(legs)
        assert all(
            not (
                leg.mode == MobilityMode.WALK
                and leg.from_node_id == leg.to_node_id
            )
            for leg in out
        )
        assert [leg.mode for leg in out] == [
            MobilityMode.METRO,
            MobilityMode.AUTO_RICKSHAW,
        ]
        steps = build_journey_steps(_journey(out), destination_label="Office")
        # Stronger: no walk LEG remains.
        assert not any(s.type == "LEG" and s.mode == "walk" for s in steps)

    def test_zero_distance_station_to_access_dest_dropped(self):
        legs = [
            _leg(
                index=0,
                mode=MobilityMode.METRO,
                from_id="station:a",
                to_id="station:x",
                from_ref="a",
                to_ref="x",
                distance_meters=3000.0,
                route_id="purple",
            ),
            _leg(
                index=1,
                mode=MobilityMode.WALK,
                from_id="station:x",
                to_id="access:destination",
                from_ref="x",
                to_ref=None,
                distance_meters=0.0,
                segment_role=SegmentRole.EGRESS,
            ),
        ]
        assert is_null_movement_leg(legs[1])
        out = collapse_null_movement_legs(legs)
        assert len(out) == 1
        assert out[0].mode == MobilityMode.METRO

    def test_metro_auto_metro_same_station_no_fake_transfer(self):
        x = "station:interchange"
        legs = [
            _leg(
                index=0,
                mode=MobilityMode.METRO,
                from_id="station:a",
                to_id=x,
                from_ref="a",
                to_ref="x",
                distance_meters=2000.0,
                route_id="purple",
            ),
            _leg(
                index=1,
                mode=MobilityMode.AUTO_RICKSHAW,
                from_id=x,
                to_id=x,
                from_ref="x",
                to_ref="x",
                distance_meters=0.0,
                is_transfer=True,
            ),
            _leg(
                index=2,
                mode=MobilityMode.METRO,
                from_id=x,
                to_id="station:b",
                from_ref="x",
                to_ref="b",
                distance_meters=2500.0,
                route_id="purple",
                is_transfer=True,
            ),
        ]
        out = normalize_journey_legs(legs)
        assert all(leg.mode != MobilityMode.AUTO_RICKSHAW for leg in out)
        # Same-route metros merge — no fake road transfer away from station.
        assert len(out) == 1
        assert out[0].mode == MobilityMode.METRO
        assert out[0].from_node_id == "station:a"
        assert out[0].to_node_id == "station:b"
        steps = build_journey_steps(_journey(out))
        assert not any(s.type == "TRANSFER" for s in steps)
        assert not any(
            s.mode in {"auto", "auto_rickshaw"} for s in steps if s.type == "LEG"
        )

    def test_legitimate_metro_walk_destination_kept(self):
        legs = [
            _leg(
                index=0,
                mode=MobilityMode.METRO,
                from_id="station:a",
                to_id="station:x",
                from_ref="a",
                to_ref="x",
                distance_meters=4000.0,
                route_id="purple",
                segment_role=SegmentRole.TRANSIT,
            ),
            _leg(
                index=1,
                mode=MobilityMode.WALK,
                from_id="station:x",
                to_id="access:destination",
                from_ref="x",
                to_ref=None,
                from_name="Station X",
                to_name="Office",
                distance_meters=200.0,
                segment_role=SegmentRole.EGRESS,
            ),
        ]
        out = normalize_journey_legs(legs)
        assert len(out) == 2
        assert out[1].mode == MobilityMode.WALK
        assert out[1].distance_meters == 200.0
        assert out[1].to_node_id == "access:destination"

    def test_legitimate_walk_bus_and_auto_metro_kept(self):
        walk_bus = [
            _leg(
                index=0,
                mode=MobilityMode.WALK,
                from_id="access:origin",
                to_id="stop:s1",
                distance_meters=150.0,
                segment_role=SegmentRole.ACCESS,
            ),
            _leg(
                index=1,
                mode=MobilityMode.BUS,
                from_id="stop:s1",
                to_id="stop:s2",
                from_ref="s1",
                to_ref="s2",
                distance_meters=5000.0,
                route_id="500D",
            ),
        ]
        assert len(normalize_journey_legs(walk_bus)) == 2

        auto_metro = [
            _leg(
                index=0,
                mode=MobilityMode.AUTO_RICKSHAW,
                from_id="access:origin",
                to_id="station:x",
                distance_meters=900.0,
                segment_role=SegmentRole.ACCESS,
            ),
            _leg(
                index=1,
                mode=MobilityMode.METRO,
                from_id="station:x",
                to_id="station:y",
                from_ref="x",
                to_ref="y",
                distance_meters=6000.0,
                route_id="green",
            ),
        ]
        assert len(normalize_journey_legs(auto_metro)) == 2
