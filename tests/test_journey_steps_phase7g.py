"""Phase 7G — grounded journey steps + transfer points."""

from __future__ import annotations

from copy import deepcopy

from src.agent.mobility_strategy import MobilityStrategy  # noqa: F401 — import order
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate
from src.journey_builder.models import EdgeKind, Journey, JourneyLeg, SegmentRole
from src.journey_builder.steps import (
    attach_steps_to_top_selection,
    build_journey_steps,
    display_mode_label,
    humanize_place_name,
)
from src.network.models import MobilityMode


def _rc(
    route_id: str,
    *,
    mode: str,
    component_modes: list[str],
    travel_time_minutes: float = 40,
    cost: float = 50,
) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        mode=mode,
        travel_time_minutes=travel_time_minutes,
        cost=cost,
        walking_minutes=5,
        transfers=0,
        congestion_score=0.2,
        reliability_score=0.9,
        disruption_risk=0.1,
        component_modes=component_modes,
        mode_signature=" → ".join(component_modes),
        walking_distance_meters=300,
    )


def _leg(
    index: int,
    mode: MobilityMode,
    from_id: str,
    to_id: str,
    *,
    from_name: str | None = None,
    to_name: str | None = None,
    edge_kind: EdgeKind = EdgeKind.BUS,
    route_id: str | None = None,
    is_transfer: bool = False,
    segment_role: SegmentRole = SegmentRole.OTHER,
) -> JourneyLeg:
    if mode == MobilityMode.WALK:
        edge_kind = EdgeKind.WALK
    elif mode in (MobilityMode.AUTO_RICKSHAW, MobilityMode.CAB):
        edge_kind = EdgeKind.ROAD_ACCESS
    return JourneyLeg(
        index=index,
        mode=mode,
        from_node_id=from_id,
        to_node_id=to_id,
        edge_id=f"e{index}",
        edge_kind=edge_kind,
        from_name=from_name,
        to_name=to_name,
        route_id=route_id,
        is_transfer=is_transfer,
        segment_role=segment_role,
    )


def _journey(legs: list[JourneyLeg], candidate_id: str = "j1") -> Journey:
    modes = [leg.mode.value for leg in legs]
    return Journey(
        candidate_id=candidate_id,
        origin=(12.8, 77.6),
        destination=(12.9, 77.5),
        legs=legs,
        transfer_count=0,
        walking_distance_meters=200,
        transit_leg_count=sum(
            1 for l in legs if l.mode in (MobilityMode.BUS, MobilityMode.METRO)
        ),
        road_leg_count=sum(
            1
            for l in legs
            if l.mode in (MobilityMode.AUTO_RICKSHAW, MobilityMode.CAB)
        ),
        modes=modes,
        snapshot_versions={},
        provenance_sources=[],
        mode_signature=" → ".join(modes),
    )


def _step_types(steps):
    return [s.type for s in steps]


def _instructions(steps):
    return [s.instruction for s in steps]


def test_walk_bus_walk_legs():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.WALK,
                "access:origin",
                "stop:ec",
                to_name="Electronic City",
                segment_role=SegmentRole.ACCESS,
            ),
            _leg(
                1,
                MobilityMode.BUS,
                "stop:ec",
                "stop:maj",
                from_name="Electronic City",
                to_name="Majestic",
                route_id="500D",
            ),
            _leg(
                2,
                MobilityMode.WALK,
                "stop:maj",
                "access:destination",
                from_name="Majestic",
                segment_role=SegmentRole.EGRESS,
            ),
        ]
    )
    steps = build_journey_steps(j)
    assert _step_types(steps) == ["LEG", "LEG", "LEG"]
    assert "Electronic City" in steps[0].instruction
    assert "Majestic" in steps[1].instruction
    assert "destination" in steps[2].instruction.lower()
    assert not any(s.type == "TRANSFER" for s in steps)


def test_bus_only_no_transfer():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", from_name="A", to_name="B"),
        ]
    )
    steps = build_journey_steps(j)
    assert all(s.type == "LEG" for s in steps)
    assert len(steps) == 1


def test_bus_metro_creates_transfer():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.BUS,
                "stop:ec",
                "stop:maj",
                from_name="Electronic City",
                to_name="Majestic",
            ),
            _leg(
                1,
                MobilityMode.METRO,
                "station:maj",
                "station:indi",
                from_name="Majestic",
                to_name="Indiranagar",
            ),
        ]
    )
    steps = build_journey_steps(j)
    assert "TRANSFER" in _step_types(steps)
    xfer = next(s for s in steps if s.type == "TRANSFER")
    assert "Bus" in xfer.instruction
    assert "Metro" in xfer.instruction
    assert "Majestic" in xfer.instruction
    assert xfer.location_name == "Majestic"


def test_metro_bus_creates_transfer():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.METRO,
                "station:a",
                "station:b",
                from_name="Indiranagar",
                to_name="Yeshwanthpur",
            ),
            _leg(
                1,
                MobilityMode.BUS,
                "stop:b",
                "stop:c",
                from_name="Yeshwanthpur",
                to_name="Destination Area",
            ),
        ]
    )
    steps = build_journey_steps(j)
    xfer = next(s for s in steps if s.type == "TRANSFER")
    assert "Metro" in xfer.instruction and "Bus" in xfer.instruction
    assert "Yeshwanthpur" in xfer.instruction


def test_auto_metro_creates_transfer():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.AUTO_RICKSHAW,
                "access:origin",
                "station:yel",
                to_name="Yelachenahalli",
                segment_role=SegmentRole.ACCESS,
            ),
            _leg(
                1,
                MobilityMode.METRO,
                "station:yel",
                "station:maj",
                from_name="Yelachenahalli",
                to_name="Majestic",
            ),
            _leg(
                2,
                MobilityMode.WALK,
                "station:maj",
                "access:destination",
                segment_role=SegmentRole.EGRESS,
            ),
        ]
    )
    steps = build_journey_steps(j)
    assert any("Change from Auto to Metro" in s.instruction for s in steps)
    assert any("Yelachenahalli" in s.instruction for s in steps if s.type == "TRANSFER")


def test_metro_walk_no_transfer():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.METRO,
                "station:a",
                "station:b",
                from_name="Majestic",
                to_name="Indiranagar",
            ),
            _leg(
                1,
                MobilityMode.WALK,
                "station:b",
                "access:destination",
                from_name="Indiranagar",
                segment_role=SegmentRole.EGRESS,
            ),
        ]
    )
    steps = build_journey_steps(j)
    assert all(s.type == "LEG" for s in steps)


def test_bus_bus_follows_transfer_semantics():
    same_route = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", to_name="Stop B", route_id="R1"),
            _leg(1, MobilityMode.BUS, "b", "c", from_name="Stop B", to_name="Stop C", route_id="R1"),
        ]
    )
    assert all(s.type == "LEG" for s in build_journey_steps(same_route))

    service_change = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", to_name="Majestic", route_id="R1"),
            _leg(
                1,
                MobilityMode.BUS,
                "b",
                "c",
                from_name="Majestic",
                to_name="Whitefield",
                route_id="R2",
                is_transfer=True,
            ),
        ]
    )
    steps = build_journey_steps(service_change)
    xfer = next(s for s in steps if s.type == "TRANSFER")
    assert "Change buses" in xfer.instruction
    assert "Majestic" in xfer.instruction


def test_transfer_at_shared_node_name():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "stop:1", "stop:hub", to_name="Majestic"),
            _leg(1, MobilityMode.METRO, "station:hub", "station:2", from_name="Majestic", to_name="Indiranagar"),
        ]
    )
    xfer = next(s for s in build_journey_steps(j) if s.type == "TRANSFER")
    assert xfer.location_name == "Majestic"
    assert xfer.from_node_id == "stop:hub"


def test_uses_actual_stop_station_names():
    j = _journey(
        [
            _leg(0, MobilityMode.WALK, "access:origin", "stop:ec", to_name="Electronic City"),
            _leg(1, MobilityMode.BUS, "stop:ec", "stop:maj", from_name="Electronic City", to_name="Majestic"),
        ]
    )
    steps = build_journey_steps(j)
    joined = " ".join(_instructions(steps))
    assert "Electronic City" in joined
    assert "Majestic" in joined


def test_node_ids_not_displayed_as_names():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "stop:20921", "stop:abc", from_name="20921", to_name=None),
        ]
    )
    steps = build_journey_steps(j)
    text = " ".join(_instructions(steps))
    assert "20921" not in text
    assert "Unknown" not in text
    assert steps[0].instruction == "Continue by Bus"


def test_missing_name_no_unknown():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b"),
            _leg(1, MobilityMode.METRO, "b", "c"),
        ]
    )
    steps = build_journey_steps(j)
    text = " ".join(_instructions(steps))
    assert "Unknown" not in text
    xfer = next(s for s in steps if s.type == "TRANSFER")
    assert xfer.instruction == "Change from Bus to Metro"


def test_multi_transfer_journey():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(1, MobilityMode.METRO, "b", "c", from_name="Majestic", to_name="Yeshwanthpur"),
            _leg(2, MobilityMode.BUS, "c", "d", from_name="Yeshwanthpur", to_name="Hebbal"),
        ]
    )
    steps = build_journey_steps(j)
    transfers = [s for s in steps if s.type == "TRANSFER"]
    assert len(transfers) == 2
    assert "Majestic" in transfers[0].instruction
    assert "Yeshwanthpur" in transfers[1].instruction


def test_ordering_preserved():
    j = _journey(
        [
            _leg(0, MobilityMode.WALK, "access:origin", "a", to_name="Electronic City"),
            _leg(1, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(2, MobilityMode.METRO, "b", "c", to_name="Indiranagar"),
            _leg(3, MobilityMode.WALK, "c", "access:destination", segment_role=SegmentRole.EGRESS),
        ]
    )
    steps = build_journey_steps(j)
    assert [s.type for s in steps] == ["LEG", "LEG", "TRANSFER", "LEG", "LEG"]
    assert steps[0].mode == "walk"
    assert steps[1].mode == "bus"
    assert steps[3].mode == "metro"
    assert steps[4].mode == "walk"


def test_steps_deterministic():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(1, MobilityMode.METRO, "b", "c", from_name="Majestic", to_name="Indiranagar"),
        ]
    )
    a = [s.to_dict() for s in build_journey_steps(j)]
    b = [s.to_dict() for s in build_journey_steps(j)]
    assert a == b


def test_top5_each_receive_own_steps():
    j_bus = _journey(
        [
            _leg(0, MobilityMode.WALK, "access:origin", "a", to_name="Electronic City"),
            _leg(1, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(2, MobilityMode.WALK, "b", "access:destination", segment_role=SegmentRole.EGRESS),
        ],
        candidate_id="bus1",
    )
    j_hybrid = _journey(
        [
            _leg(0, MobilityMode.AUTO_RICKSHAW, "access:origin", "s", to_name="Yelachenahalli"),
            _leg(1, MobilityMode.METRO, "s", "m", from_name="Yelachenahalli", to_name="Majestic"),
            _leg(2, MobilityMode.WALK, "m", "access:destination", segment_role=SegmentRole.EGRESS),
        ],
        candidate_id="metro1",
    )
    result = evaluate_routes(
        [
            _rc(
                "bus1",
                mode="bus",
                component_modes=["walk", "bus", "walk"],
                travel_time_minutes=50,
                cost=20,
            ),
            _rc(
                "metro1",
                mode="hybrid",
                component_modes=["auto", "metro", "walk"],
                travel_time_minutes=40,
                cost=45,
            ),
        ]
    )
    top = deepcopy(result.top_selection)
    enriched = attach_steps_to_top_selection(top, [j_bus, j_hybrid])
    assert enriched is not None
    by_id = {o["candidate_id"]: o for o in enriched["top_journeys"]}
    bus_steps = by_id["bus1"]["steps"]
    metro_steps = by_id["metro1"]["steps"]
    assert any(s["type"] == "LEG" for s in bus_steps)
    assert not any(s["type"] == "TRANSFER" for s in bus_steps)
    assert any(s["type"] == "TRANSFER" for s in metro_steps)
    assert any("Yelachenahalli" in s["instruction"] for s in metro_steps)


def test_no_ranking_change_from_steps():
    result = evaluate_routes(
        [
            _rc(
                "a",
                mode="bus",
                component_modes=["bus"],
                travel_time_minutes=40,
                cost=20,
            ),
            _rc(
                "b",
                mode="metro",
                component_modes=["metro"],
                travel_time_minutes=35,
                cost=40,
            ),
        ]
    )
    before = deepcopy(result.top_selection)
    j = _journey([_leg(0, MobilityMode.METRO, "x", "y", to_name="X")], candidate_id="b")
    after = attach_steps_to_top_selection(deepcopy(before), [j])
    assert before["recommended"]["route_id"] == after["recommended"]["route_id"]
    assert [o["route_id"] for o in before["top_journeys"]] == [
        o["route_id"] for o in after["top_journeys"]
    ]
    assert before["recommended"]["score"] == after["recommended"]["score"]


def test_humanize_and_display_labels():
    assert humanize_place_name("electronic_city") == "Electronic City"
    assert humanize_place_name("20921") is None
    assert humanize_place_name("unknown") is None
    assert display_mode_label("bmtc") == "Bus"
    assert display_mode_label("bmrcl") == "Metro"
    assert display_mode_label("auto_rickshaw") == "Auto"


def test_journey_to_dict_includes_steps():
    j = _journey(
        [
            _leg(0, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(1, MobilityMode.METRO, "b", "c", from_name="Majestic", to_name="Indiranagar"),
        ]
    )
    d = j.to_dict()
    assert "steps" in d
    assert any(s["type"] == "TRANSFER" for s in d["steps"])


def test_walk_access_egress_not_transfer():
    j = _journey(
        [
            _leg(0, MobilityMode.WALK, "access:origin", "a", to_name="Stop", segment_role=SegmentRole.ACCESS),
            _leg(1, MobilityMode.BUS, "a", "b", to_name="Majestic"),
            _leg(2, MobilityMode.WALK, "b", "access:destination", segment_role=SegmentRole.EGRESS),
        ]
    )
    assert all(s.type == "LEG" for s in build_journey_steps(j))


def test_cab_only_no_transfer():
    j = _journey(
        [
            _leg(
                0,
                MobilityMode.CAB,
                "access:origin",
                "access:destination",
                segment_role=SegmentRole.FULL_JOURNEY_ROAD,
            ),
        ]
    )
    steps = build_journey_steps(j)
    assert len(steps) == 1
    assert steps[0].type == "LEG"
    assert "Cab" in steps[0].instruction or "cab" in steps[0].instruction.lower()
