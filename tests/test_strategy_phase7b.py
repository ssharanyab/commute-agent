"""Phase 7B — strategy-aware selection + hard constraints."""

from __future__ import annotations

from typing import List, Optional

from src.agent.mobility_strategy import (
    AccessoryMode,
    MobilityConstraints,
    MobilityStrategy,
)
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import (
    PROFILE_BALANCED,
    PROFILE_FASTEST,
    PROFILE_LOW_WALKING,
    RouteCandidate,
    preference_profile,
)
from src.decision_engine.strategy import (
    BackboneKind,
    classify_backbone,
    has_public_transport_backbone,
    has_road_transport_backbone,
    validate_mobility_constraints,
)


def _rc(
    route_id: str,
    *,
    mode: str,
    component_modes: List[str],
    travel_time_minutes: float = 40,
    cost: float = 50,
    walking_minutes: float = 5,
    transfers: int = 0,
    walking_distance_meters: Optional[float] = 400,
    congestion_score: float = 0.3,
    reliability_score: float = 0.8,
    cost_status: str = "known",
    duration_status: str = "known",
) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        mode=mode,
        travel_time_minutes=travel_time_minutes,
        cost=cost,
        walking_minutes=walking_minutes,
        transfers=transfers,
        congestion_score=congestion_score,
        reliability_score=reliability_score,
        disruption_risk=0.1,
        component_modes=component_modes,
        mode_signature=" → ".join(component_modes),
        walking_distance_meters=walking_distance_meters,
        access_walking_meters=walking_distance_meters,
        transfer_walking_meters=0.0,
        egress_walking_meters=0.0,
        cost_status=cost_status,
        duration_status=duration_status,
    )


def _pool():
    """Diverse candidate set for strategy tests."""
    return [
        _rc(
            "auto_only",
            mode="auto_rickshaw",
            component_modes=["auto_rickshaw"],
            travel_time_minutes=35,
            cost=200,
            walking_minutes=0,
            walking_distance_meters=0,
            transfers=0,
        ),
        _rc(
            "cab_only",
            mode="cab",
            component_modes=["cab"],
            travel_time_minutes=30,
            cost=420,
            walking_minutes=0,
            walking_distance_meters=0,
            transfers=0,
        ),
        _rc(
            "bus_pt",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=55,
            cost=25,
            walking_minutes=8,
            walking_distance_meters=600,
            transfers=0,
        ),
        _rc(
            "metro_pt",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=42,
            cost=40,
            walking_minutes=12,
            walking_distance_meters=900,
            transfers=0,
        ),
        _rc(
            "bus_metro_pt",
            mode="hybrid",
            component_modes=["walk", "bus", "metro", "walk"],
            travel_time_minutes=48,
            cost=45,
            walking_minutes=10,
            walking_distance_meters=700,
            transfers=1,
        ),
        _rc(
            "auto_bus_pt",
            mode="hybrid",
            component_modes=["auto_rickshaw", "bus", "walk"],
            travel_time_minutes=50,
            cost=80,
            walking_minutes=3,
            walking_distance_meters=200,
            transfers=1,
        ),
        _rc(
            "metro_auto_pt",
            mode="hybrid",
            component_modes=["walk", "metro", "auto_rickshaw"],
            travel_time_minutes=45,
            cost=90,
            walking_minutes=4,
            walking_distance_meters=250,
            transfers=1,
        ),
        _rc(
            "cab_metro",
            mode="hybrid",
            component_modes=["cab", "metro", "walk"],
            travel_time_minutes=38,
            cost=250,
            walking_minutes=5,
            walking_distance_meters=300,
            transfers=1,
        ),
        _rc(
            "auto_cab_road",
            mode="hybrid",
            component_modes=["auto_rickshaw", "cab"],
            travel_time_minutes=28,
            cost=500,
            walking_minutes=0,
            walking_distance_meters=0,
            transfers=1,
        ),
    ]


class TestBackboneClassification:
    def test_pt_backbone_variants(self):
        assert has_public_transport_backbone(
            _rc("a", mode="bus", component_modes=["walk", "bus", "walk"])
        )
        assert has_public_transport_backbone(
            _rc("b", mode="metro", component_modes=["walk", "metro", "walk"])
        )
        assert has_public_transport_backbone(
            _rc("c", mode="hybrid", component_modes=["walk", "bus", "metro", "walk"])
        )
        assert has_public_transport_backbone(
            _rc("d", mode="hybrid", component_modes=["auto_rickshaw", "bus", "walk"])
        )
        assert has_public_transport_backbone(
            _rc("e", mode="hybrid", component_modes=["walk", "metro", "auto_rickshaw"])
        )

    def test_non_pt_backbone(self):
        assert not has_public_transport_backbone(
            _rc("a", mode="auto_rickshaw", component_modes=["auto_rickshaw"])
        )
        assert not has_public_transport_backbone(
            _rc("b", mode="cab", component_modes=["cab"])
        )
        assert classify_backbone(
            _rc("c", mode="cab", component_modes=["cab"])
        ) == BackboneKind.ROAD


class TestPublicTransportOnly:
    def test_rejects_road(self):
        auto = _rc("a", mode="auto_rickshaw", component_modes=["auto_rickshaw"])
        cab = _rc("b", mode="cab", component_modes=["cab"])
        auto_metro = _rc(
            "c", mode="hybrid", component_modes=["auto_rickshaw", "metro", "walk"]
        )
        for c in (auto, cab, auto_metro):
            v = validate_mobility_constraints(
                c,
                strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY,
                constraints=None,
            )
            assert v, c.route_id

    def test_accepts_walk_metro_and_bus_metro(self):
        for c in (
            _rc("m", mode="metro", component_modes=["walk", "metro", "walk"]),
            _rc("b", mode="hybrid", component_modes=["walk", "bus", "metro", "walk"]),
        ):
            assert not validate_mobility_constraints(
                c,
                strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY,
                constraints=None,
            )


class TestAccessoryAllowList:
    def test_pt_first_walk_auto_permits_auto_metro_walk(self):
        c = _rc(
            "x",
            mode="hybrid",
            component_modes=["auto_rickshaw", "metro", "walk"],
        )
        constraints = MobilityConstraints(
            allowed_accessory_modes=[AccessoryMode.WALK, AccessoryMode.AUTO]
        )
        assert not validate_mobility_constraints(
            c,
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=constraints,
        )

    def test_pt_first_walk_only_rejects_auto_metro(self):
        c = _rc(
            "x",
            mode="hybrid",
            component_modes=["auto_rickshaw", "metro", "walk"],
        )
        constraints = MobilityConstraints(
            allowed_accessory_modes=[AccessoryMode.WALK]
        )
        v = validate_mobility_constraints(
            c,
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=constraints,
        )
        assert any("ACCESSORY_MODE_NOT_ALLOWED" in x for x in v)

    def test_pt_first_walk_auto_rejects_cab_metro(self):
        c = _rc("x", mode="hybrid", component_modes=["cab", "metro", "walk"])
        constraints = MobilityConstraints(
            allowed_accessory_modes=[AccessoryMode.WALK, AccessoryMode.AUTO]
        )
        v = validate_mobility_constraints(
            c,
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=constraints,
        )
        assert any("ACCESSORY_MODE_NOT_ALLOWED" in x for x in v)

    def test_unset_accessory_preserves_behavior(self):
        c = _rc("x", mode="hybrid", component_modes=["cab", "metro", "walk"])
        assert not validate_mobility_constraints(
            c,
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=MobilityConstraints(),
        )


class TestWalkingAndTransfers:
    def test_walking_below_limit_accepted(self):
        c = _rc(
            "x",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            walking_distance_meters=600,
        )
        v = validate_mobility_constraints(
            c,
            strategy=None,
            constraints=MobilityConstraints(max_walking_distance_meters=1000),
        )
        assert not v

    def test_walking_above_limit_rejected(self):
        c = _rc(
            "x",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            walking_distance_meters=1500,
        )
        v = validate_mobility_constraints(
            c,
            strategy=None,
            constraints=MobilityConstraints(max_walking_distance_meters=1000),
        )
        assert any("EXCEEDS_MAX_WALKING_DISTANCE" in x for x in v)

    def test_unknown_walking_rejected_safely(self):
        c = _rc(
            "x",
            mode="bus",
            component_modes=["walk", "bus"],
            walking_minutes=10,
            walking_distance_meters=None,
        )
        c.access_walking_meters = None
        c.transfer_walking_meters = None
        c.egress_walking_meters = None
        v = validate_mobility_constraints(
            c,
            strategy=None,
            constraints=MobilityConstraints(max_walking_distance_meters=1000),
        )
        assert any("UNKNOWN_WALKING_DISTANCE" in x for x in v)

    def test_aggregated_walking_legs(self):
        c = _rc(
            "x",
            mode="hybrid",
            component_modes=["walk", "bus", "walk"],
            walking_distance_meters=None,
        )
        c.access_walking_meters = 200
        c.transfer_walking_meters = 100
        c.egress_walking_meters = 300
        v = validate_mobility_constraints(
            c,
            strategy=None,
            constraints=MobilityConstraints(max_walking_distance_meters=500),
        )
        assert any("EXCEEDS_MAX_WALKING_DISTANCE" in x for x in v)

    def test_transfer_limit(self):
        ok = _rc(
            "ok",
            mode="hybrid",
            component_modes=["walk", "bus", "metro", "walk"],
            transfers=1,
        )
        bad = _rc(
            "bad",
            mode="hybrid",
            component_modes=["walk", "bus", "metro", "bus", "walk"],
            transfers=3,
        )
        constraints = MobilityConstraints(max_transfers=2)
        assert not validate_mobility_constraints(
            ok, strategy=None, constraints=constraints
        )
        assert any(
            "EXCEEDS_MAX_TRANSFERS" in x
            for x in validate_mobility_constraints(
                bad, strategy=None, constraints=constraints
            )
        )


class TestStrategySelection:
    def test_agent_decides_matches_baseline(self):
        pool = _pool()
        prefs = preference_profile(PROFILE_FASTEST)
        baseline = evaluate_routes(pool, prefs)
        agent = evaluate_routes(
            pool, prefs, strategy=MobilityStrategy.AGENT_DECIDES
        )
        assert baseline.recommended_route.route_id == agent.recommended_route.route_id

    def test_pt_first_selects_pt_backbone(self):
        pool = _pool()
        # Cab is fastest overall; PT-first must still pick a PT backbone.
        res = evaluate_routes(
            pool,
            preference_profile(PROFILE_FASTEST),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
        )
        assert res.recommended_route is not None
        assert has_public_transport_backbone(res.recommended_route)
        assert res.recommended_route.route_id != "cab_only"
        assert res.recommended_route.route_id != "auto_only"

    def test_pt_first_fastest_among_pt(self):
        pool = _pool()
        res = evaluate_routes(
            pool,
            preference_profile(PROFILE_FASTEST),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=MobilityConstraints(
                allowed_accessory_modes=[
                    AccessoryMode.WALK,
                    AccessoryMode.AUTO,
                    AccessoryMode.CAB,
                ]
            ),
        )
        # Among PT with accessories allowed, cab→metro (38) is fastest PT-backbone.
        assert res.recommended_route.route_id == "cab_metro"

    def test_pt_first_low_walking_among_pt(self):
        pool = _pool()
        res = evaluate_routes(
            pool,
            preference_profile(PROFILE_LOW_WALKING),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=MobilityConstraints(
                allowed_accessory_modes=[AccessoryMode.WALK, AccessoryMode.AUTO]
            ),
        )
        assert has_public_transport_backbone(res.recommended_route)
        # auto_bus_pt has 200m walking — lowest among allowed PT set.
        assert res.recommended_route.walking_distance_meters <= 600

    def test_pt_first_balanced_among_pt(self):
        pool = _pool()
        res = evaluate_routes(
            pool,
            preference_profile(PROFILE_BALANCED),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=MobilityConstraints(
                allowed_accessory_modes=[AccessoryMode.WALK, AccessoryMode.AUTO]
            ),
        )
        assert has_public_transport_backbone(res.recommended_route)

    def test_metro_vs_bus_dynamic(self):
        bus = _rc(
            "bus",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=47,
            cost=20,
            walking_minutes=4,
            walking_distance_meters=300,
            transfers=0,
        )
        metro = _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            cost=35,
            walking_minutes=15,
            walking_distance_meters=1200,
            transfers=1,
        )
        fastest = evaluate_routes(
            [bus, metro],
            preference_profile(PROFILE_FASTEST),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
        )
        low_walk = evaluate_routes(
            [bus, metro],
            preference_profile(PROFILE_LOW_WALKING),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
        )
        assert fastest.recommended_route.route_id == "metro"
        assert low_walk.recommended_route.route_id == "bus"

    def test_road_first_prefers_road(self):
        pool = _pool()
        res = evaluate_routes(
            pool,
            preference_profile(PROFILE_FASTEST),
            strategy=MobilityStrategy.ROAD_TRANSPORT_FIRST,
        )
        assert has_road_transport_backbone(res.recommended_route)

    def test_pt_only_no_valid_when_only_road(self):
        res = evaluate_routes(
            [
                _rc("a", mode="cab", component_modes=["cab"], walking_distance_meters=0),
                _rc(
                    "b",
                    mode="auto_rickshaw",
                    component_modes=["auto_rickshaw"],
                    walking_distance_meters=0,
                ),
            ],
            preference_profile(PROFILE_BALANCED),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY,
        )
        assert res.recommended_route is None
        assert "NO_VALID_ROUTE" in res.reason_codes

    def test_walking_constraint_blocks_faster_long_walk(self):
        short = _rc(
            "short",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=60,
            walking_distance_meters=400,
        )
        long_fast = _rc(
            "long",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            walking_distance_meters=1500,
        )
        res = evaluate_routes(
            [short, long_fast],
            preference_profile(PROFILE_FASTEST),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
            constraints=MobilityConstraints(max_walking_distance_meters=1000),
        )
        assert res.recommended_route.route_id == "short"

    def test_strategy_meta_populated(self):
        res = evaluate_routes(
            _pool(),
            preference_profile(PROFILE_BALANCED),
            strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
        )
        assert res.strategy_meta is not None
        assert res.strategy_meta["strategy_applied"] == "PUBLIC_TRANSPORT_FIRST"
        assert "backbone_by_route_id" in res.strategy_meta
