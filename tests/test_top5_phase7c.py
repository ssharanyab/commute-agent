"""Phase 7C — Top-5 selection, diversity signatures, grounded reasons."""

from __future__ import annotations

import re
from typing import List, Optional

from src.agent.mobility_strategy import MobilityConstraints, MobilityStrategy
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import (
    PROFILE_BALANCED,
    PROFILE_CHEAPEST,
    PROFILE_FASTEST,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    RouteCandidate,
    preference_profile,
)
from src.decision_engine.top5 import (
    MAX_TOP_JOURNEYS,
    diversity_signature,
    select_top_journeys,
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
        cost_status=cost_status,
        duration_status=duration_status,
    )


# ---------------------------------------------------------------------------
# Diversity signature
# ---------------------------------------------------------------------------


def test_diversity_signature_normalizes_aliases():
    a = _rc("a", mode="hybrid", component_modes=["walking", "bmtc", "walking"])
    b = _rc("b", mode="hybrid", component_modes=["walk", "bus", "walk"])
    assert diversity_signature(a) == "walk|bus|walk"
    assert diversity_signature(b) == "walk|bus|walk"


def test_diversity_signature_distinguishes_bus_metro_and_combo():
    bus = _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"])
    metro = _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"])
    combo = _rc(
        "combo", mode="hybrid", component_modes=["walk", "bus", "metro", "walk"]
    )
    assert diversity_signature(bus) == "walk|bus|walk"
    assert diversity_signature(metro) == "walk|metro|walk"
    assert diversity_signature(combo) == "walk|bus|metro|walk"
    assert len({diversity_signature(bus), diversity_signature(metro), diversity_signature(combo)}) == 3


def test_diversity_signature_distinguishes_first_mile():
    auto_metro = _rc(
        "am", mode="hybrid", component_modes=["auto", "metro", "walk"]
    )
    walk_metro = _rc(
        "wm", mode="hybrid", component_modes=["walk", "metro", "walk"]
    )
    assert diversity_signature(auto_metro) != diversity_signature(walk_metro)


# ---------------------------------------------------------------------------
# Basic selection
# ---------------------------------------------------------------------------


def test_one_candidate_one_result():
    result = evaluate_routes([_rc("only", mode="cab", component_modes=["cab"])])
    top = result.top_selection
    assert top["selected_count"] == 1
    assert top["top_journeys"][0]["route_id"] == "only"
    assert top["top_journeys"][0]["is_recommended"] is True
    assert top["top_journeys"][0]["rank"] == 1


def test_three_candidates_three_results():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=30, cost=400),
        _rc(
            "bus",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=50,
            cost=25,
        ),
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            cost=40,
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_BALANCED))
    assert result.top_selection["selected_count"] == 3
    assert len(result.top_selection["top_journeys"]) == 3


def test_ten_candidates_max_five():
    cands = []
    # Distinct signatures
    templates = [
        (["cab"], "cab"),
        (["auto"], "auto"),
        (["walk", "bus", "walk"], "bus"),
        (["walk", "metro", "walk"], "metro"),
        (["walk", "bus", "metro", "walk"], "hybrid"),
        (["auto", "bus", "walk"], "hybrid"),
        (["auto", "metro", "walk"], "hybrid"),
        (["auto", "metro", "auto"], "hybrid"),
        (["walk", "metro", "auto"], "hybrid"),
        (["cab", "walk"], "cab"),
    ]
    for i, (modes, mode) in enumerate(templates):
        cands.append(
            _rc(
                f"r{i}",
                mode=mode,
                component_modes=modes,
                travel_time_minutes=30 + i,
                cost=50 + i * 10,
            )
        )
    result = evaluate_routes(cands)
    assert result.top_selection["selected_count"] == MAX_TOP_JOURNEYS
    assert len(result.top_selection["top_journeys"]) == 5


def test_authoritative_recommendation_is_first():
    cands = [
        _rc("slow_cheap", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=60, cost=20),
        _rc("fast", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=35, cost=45),
        _rc("mid", mode="cab", component_modes=["cab"], travel_time_minutes=40, cost=300),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    assert result.recommended_route is not None
    assert result.top_selection["top_journeys"][0]["route_id"] == result.recommended_route.route_id
    assert result.top_selection["top_journeys"][0]["is_recommended"] is True


def test_invalid_candidates_never_appear():
    cands = [
        _rc("ok", mode="bus", component_modes=["walk", "bus", "walk"], walking_distance_meters=400),
        _rc(
            "too_much_walk",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            walking_distance_meters=5000,
            travel_time_minutes=30,
        ),
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=25),
    ]
    result = evaluate_routes(
        cands,
        strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY,
        constraints=MobilityConstraints(max_walking_distance_meters=1000),
    )
    ids = [o["route_id"] for o in result.top_selection["top_journeys"]]
    assert "too_much_walk" not in ids
    assert "cab" not in ids
    assert "ok" in ids


# ---------------------------------------------------------------------------
# Duplicate suppression
# ---------------------------------------------------------------------------


def test_duplicate_bus_signatures_collapsed():
    cands = [
        _rc(
            f"bus{i}",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=50 + i,
            cost=20 + i,
        )
        for i in range(5)
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    assert result.top_selection["selected_count"] == 1
    # Best (fastest) duplicate wins
    assert result.top_selection["top_journeys"][0]["route_id"] == "bus0"


def test_different_mode_sequences_survive():
    cands = [
        _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=50),
        _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=42),
        _rc(
            "combo",
            mode="hybrid",
            component_modes=["walk", "bus", "metro", "walk"],
            travel_time_minutes=48,
            transfers=1,
        ),
    ]
    result = evaluate_routes(cands)
    sigs = {o["diversity_signature"] for o in result.top_selection["top_journeys"]}
    assert "walk|bus|walk" in sigs
    assert "walk|metro|walk" in sigs
    assert "walk|bus|metro|walk" in sigs


def test_auto_metro_and_walk_metro_can_both_survive():
    cands = [
        _rc(
            "auto_metro",
            mode="hybrid",
            component_modes=["auto", "metro", "walk"],
            travel_time_minutes=40,
            cost=120,
        ),
        _rc(
            "walk_metro",
            mode="hybrid",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=45,
            cost=40,
        ),
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=35, cost=400),
    ]
    result = evaluate_routes(
        cands, strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST
    )
    ids = {o["route_id"] for o in result.top_selection["top_journeys"]}
    assert "auto_metro" in ids
    assert "walk_metro" in ids


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


def test_pt_first_prioritizes_pt_backbone_alternatives():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=28, cost=400),
        _rc(
            "bus",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=55,
            cost=25,
        ),
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=42,
            cost=40,
        ),
        _rc("auto", mode="auto", component_modes=["auto"], travel_time_minutes=32, cost=180),
    ]
    result = evaluate_routes(
        cands,
        preference_profile(PROFILE_FASTEST),
        strategy=MobilityStrategy.PUBLIC_TRANSPORT_FIRST,
    )
    top_ids = [o["route_id"] for o in result.top_selection["top_journeys"]]
    assert top_ids[0] in {"bus", "metro"}
    # While PT options exist, fill preferred tier first
    preferred = [o for o in result.top_selection["top_journeys"] if o["strategy_tier"] == 0]
    assert len(preferred) >= 2
    assert all(o["route_id"] in {"bus", "metro"} for o in preferred)


def test_pt_only_excludes_road_from_top5():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=25),
        _rc("auto", mode="auto", component_modes=["auto"], travel_time_minutes=30),
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
        ),
    ]
    result = evaluate_routes(
        cands, strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY
    )
    ids = [o["route_id"] for o in result.top_selection["top_journeys"]]
    assert ids == ["metro"]


def test_road_first_prioritizes_road_backbone():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=35, cost=400),
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            cost=40,
        ),
        _rc("auto", mode="auto", component_modes=["auto"], travel_time_minutes=38, cost=180),
    ]
    result = evaluate_routes(
        cands, strategy=MobilityStrategy.ROAD_TRANSPORT_FIRST
    )
    assert result.top_selection["top_journeys"][0]["route_id"] in {"cab", "auto"}
    assert result.top_selection["top_journeys"][0]["strategy_tier"] == 0


def test_agent_decides_preserves_normal_ordering():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=30, cost=400),
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=45,
            cost=40,
        ),
    ]
    with_strategy = evaluate_routes(
        cands,
        preference_profile(PROFILE_FASTEST),
        strategy=MobilityStrategy.AGENT_DECIDES,
    )
    without = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    assert with_strategy.recommended_route.route_id == without.recommended_route.route_id
    assert (
        with_strategy.top_selection["top_journeys"][0]["route_id"]
        == without.top_selection["top_journeys"][0]["route_id"]
    )


# ---------------------------------------------------------------------------
# Preference authority
# ---------------------------------------------------------------------------


def test_fastest_recommendation_remains_authoritative():
    cands = [
        _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40, cost=40),
        _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=48, cost=20),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    assert result.recommended_route.route_id == "metro"
    assert result.top_selection["top_journeys"][0]["route_id"] == "metro"


def test_cheapest_recommendation_remains_authoritative():
    cands = [
        _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40, cost=40),
        _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=48, cost=20),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_CHEAPEST))
    assert result.recommended_route.route_id == "bus"
    assert result.top_selection["top_journeys"][0]["route_id"] == "bus"


def test_low_walking_recommendation_remains_authoritative():
    cands = [
        _rc(
            "metro",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            walking_distance_meters=1200,
            walking_minutes=15,
        ),
        _rc(
            "bus",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=48,
            walking_distance_meters=300,
            walking_minutes=4,
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_LOW_WALKING))
    assert result.recommended_route.route_id == "bus"
    assert result.top_selection["top_journeys"][0]["route_id"] == "bus"


def test_balanced_remains_authoritative():
    cands = [
        _rc("a", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40, cost=40),
        _rc("b", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=47, cost=20),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_BALANCED))
    assert result.recommended_route is not None
    assert result.top_selection["top_journeys"][0]["route_id"] == result.recommended_route.route_id


# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------


def test_faster_journey_gets_grounded_faster_reason():
    cands = [
        _rc("fast", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40),
        _rc("slow", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=55),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    reason = result.top_selection["top_journeys"][0]["reason"]
    assert "faster" in reason.lower() or "fastest" in reason.lower() or "Best match" in reason


def test_lowest_cost_reason_only_when_cost_known():
    cands = [
        _rc(
            "cheap",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=50,
            cost=20,
            cost_status="known",
        ),
        _rc(
            "pricey",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            cost=80,
            cost_status="known",
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_CHEAPEST))
    # Recommended is cheap; alt may mention cost if it's the lowest among set — recommended reason
    alt = [o for o in result.top_selection["top_journeys"] if o["route_id"] == "pricey"]
    # pricey should not claim lowest-cost
    if alt:
        assert "Lowest-cost" not in alt[0]["reason"]
        assert "cheaper" not in alt[0]["reason"].lower()


def test_unknown_cost_does_not_produce_cheaper():
    cands = [
        _rc(
            "unknown_cost",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=50,
            cost=0,
            cost_status="unknown",
        ),
        _rc(
            "known",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            cost=40,
            cost_status="known",
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_CHEAPEST))
    for opt in result.top_selection["top_journeys"]:
        assert "cheaper" not in opt["reason"].lower()
        assert "Lowest-cost" not in opt["reason"] or opt["route_id"] != "unknown_cost"


def test_lower_walking_reason_when_known():
    cands = [
        _rc(
            "more_walk",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            walking_distance_meters=1200,
            walking_minutes=15,
        ),
        _rc(
            "less_walk",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=48,
            walking_distance_meters=300,
            walking_minutes=4,
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_LOW_WALKING))
    # less_walk is recommended; check alt reason mentions walking vs recommended if present
    for opt in result.top_selection["top_journeys"]:
        if opt["route_id"] == "more_walk":
            # should not claim less walking
            assert "Less walking" not in opt["reason"]
            assert "Least walking" not in opt["reason"]


def test_unknown_walking_does_not_produce_walking_comparison():
    cands = [
        _rc(
            "unk_walk",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=40,
            walking_distance_meters=None,
            walking_minutes=12,
        ),
        _rc(
            "known_walk",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=48,
            walking_distance_meters=300,
            walking_minutes=4,
        ),
    ]
    # Clear meter fields so walking is unknown for unk_walk
    cands[0].walking_distance_meters = None
    cands[0].access_walking_meters = None
    cands[0].transfer_walking_meters = None
    cands[0].egress_walking_meters = None
    result = evaluate_routes(cands, preference_profile(PROFILE_LOW_WALKING))
    for opt in result.top_selection["top_journeys"]:
        if opt["route_id"] == "unk_walk":
            assert "walking" not in opt["reason"].lower()


def test_reliability_reason_when_data_supports():
    cands = [
        _rc(
            "reliable",
            mode="metro",
            component_modes=["walk", "metro", "walk"],
            travel_time_minutes=45,
            reliability_score=0.95,
        ),
        _rc(
            "flaky",
            mode="bus",
            component_modes=["walk", "bus", "walk"],
            travel_time_minutes=40,
            reliability_score=0.4,
        ),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_RELIABLE))
    reasons = " ".join(o["reason"] for o in result.top_selection["top_journeys"])
    # At least one grounded reliability mention or preference-fit for recommended
    assert result.recommended_route.route_id == "reliable"
    assert "score" not in reasons.lower() or "More reliable" in reasons or "Best match" in reasons


def test_no_raw_scores_or_ids_in_reasons():
    cands = [
        _rc("route_alpha_99", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40),
        _rc("route_beta_88", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=50),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_BALANCED))
    for opt in result.top_selection["top_journeys"]:
        reason = opt["reason"]
        assert opt["route_id"] not in reason
        assert not re.search(r"\b\d+\.\d+\b", reason)  # no float scores
        assert "score" not in reason.lower()
        assert "gemini" not in reason.lower()
        assert "decision engine" not in reason.lower()


# ---------------------------------------------------------------------------
# Stability / edge
# ---------------------------------------------------------------------------


def test_same_input_same_top5_ordering():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=30, cost=400),
        _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=50, cost=25),
        _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=42, cost=40),
        _rc(
            "combo",
            mode="hybrid",
            component_modes=["walk", "bus", "metro", "walk"],
            travel_time_minutes=48,
            transfers=1,
            cost=45,
        ),
    ]
    a = evaluate_routes(cands, preference_profile(PROFILE_BALANCED))
    b = evaluate_routes(cands, preference_profile(PROFILE_BALANCED))
    assert [o["route_id"] for o in a.top_selection["top_journeys"]] == [
        o["route_id"] for o in b.top_selection["top_journeys"]
    ]
    assert [o["reason"] for o in a.top_selection["top_journeys"]] == [
        o["reason"] for o in b.top_selection["top_journeys"]
    ]


def test_empty_candidate_set_safe():
    result = evaluate_routes([])
    assert result.recommended_route is None
    assert result.top_selection["selected_count"] == 0
    assert result.top_selection["top_journeys"] == []


def test_no_valid_route_top5_empty():
    cands = [
        _rc("cab", mode="cab", component_modes=["cab"]),
        _rc("auto", mode="auto", component_modes=["auto"]),
    ]
    result = evaluate_routes(
        cands, strategy=MobilityStrategy.PUBLIC_TRANSPORT_ONLY
    )
    assert result.recommended_route is None
    assert "NO_VALID_ROUTE" in result.reason_codes
    assert result.top_selection["selected_count"] == 0


def test_select_top_journeys_does_not_change_winner():
    cands = [
        _rc("metro", mode="metro", component_modes=["walk", "metro", "walk"], travel_time_minutes=40),
        _rc("bus", mode="bus", component_modes=["walk", "bus", "walk"], travel_time_minutes=50),
        _rc("cab", mode="cab", component_modes=["cab"], travel_time_minutes=35),
    ]
    result = evaluate_routes(cands, preference_profile(PROFILE_FASTEST))
    winner = result.recommended_route.route_id
    again = select_top_journeys(
        result, preference_profile(PROFILE_FASTEST), strategy=None
    )
    assert again.recommended.route_id == winner
    assert again.options[0].is_recommended is True


def test_candidate_identity_preserved():
    result = evaluate_routes(
        [
            _rc("j_123", mode="metro", component_modes=["walk", "metro", "walk"]),
            _rc("j_456", mode="bus", component_modes=["walk", "bus", "walk"]),
        ]
    )
    for opt in result.top_selection["top_journeys"]:
        assert opt["route_id"]
        assert opt["candidate_id"] == opt["route_id"]
        assert opt["component_modes"]
        assert opt["diversity_signature"]
