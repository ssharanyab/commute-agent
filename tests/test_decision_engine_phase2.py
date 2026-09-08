"""
Phase 2 decision-engine tests: preference profiles, historical intelligence,
cab bias (no mode penalty), constraints, categories, replanning.
"""

from __future__ import annotations

from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import (
    RouteCandidate,
    UserPreferences,
    preference_profile,
    PROFILE_FASTEST,
    PROFILE_CHEAPEST,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    PROFILE_LOW_TRAFFIC,
    CATEGORY_BEST_OVERALL,
    CATEGORY_FASTEST,
    CATEGORY_CHEAPEST,
    CATEGORY_MOST_RELIABLE,
)
from src.decision_engine.scoring import (
    effective_reliability,
    unique_category_alternatives,
)
from src.planner.models import CommuteRequest, ContextChange, PlannerResult
from src.planner.replan import replan_commute
from tests.fixtures import get_bengaluru_test_candidates


def _cab_vs_metro_vs_bus():
    """Cab is fastest/expensive; metro cheap/reliable; bus mid with low walking."""
    return [
        RouteCandidate(
            "cab_fast",
            "cab",
            30.0,
            400.0,
            0.0,
            0,
            0.70,
            0.55,
            0.15,
            historical_mobility_signal={
                "has_historical_coverage": True,
                "historical_expected_travel_time_minutes": 28.0,
                "historical_reliability_score": 0.50,
                "confidence_level": "high",
            },
        ),
        RouteCandidate(
            "metro_cheap",
            "metro",
            55.0,
            40.0,
            12.0,
            1,
            0.15,
            0.92,
            0.05,
            historical_mobility_signal={
                "has_historical_coverage": False,
                "confidence_level": "none",
            },
        ),
        RouteCandidate(
            "bus_low_walk",
            "bus",
            50.0,
            35.0,
            2.0,
            0,
            0.35,
            0.75,
            0.10,
            historical_mobility_signal=None,
        ),
    ]


def test_fastest_profile_selects_fastest_route():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_FASTEST))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "cab_fast"
    assert "FASTEST" in res.reason_codes


def test_cheapest_profile_selects_cheaper_route():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_CHEAPEST))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id in {"metro_cheap", "bus_low_walk"}
    assert res.recommended_route.cost < 100


def test_low_walking_profile_selects_low_walking_route():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_LOW_WALKING))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id != "metro_cheap"
    assert res.recommended_route.walking_minutes <= 2.0
    # Absolute lowest walk may be cab (0); winner can be another low-walk route.
    low_walk_ids = {
        sr.route.route_id
        for sr in res.ranked_routes
        if "LOW_WALKING" in sr.reason_codes
    }
    assert "cab_fast" in low_walk_ids


def test_reliable_profile_selects_more_reliable_route():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_RELIABLE))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "metro_cheap"
    assert "HIGH_RELIABILITY" in res.reason_codes


def test_low_traffic_profile_selects_lower_congestion_route():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_LOW_TRAFFIC))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id != "cab_fast"
    assert res.recommended_route.congestion_score <= 0.35


def test_cab_not_automatic_winner_under_cost_prefs():
    routes = _cab_vs_metro_vs_bus()
    cheapest = evaluate_routes(routes, preference_profile(PROFILE_CHEAPEST))
    assert cheapest.recommended_route is not None
    assert cheapest.recommended_route.mode != "cab"


def test_cab_can_win_when_time_strongly_prioritized():
    res = evaluate_routes(_cab_vs_metro_vs_bus(), preference_profile(PROFILE_FASTEST))
    assert res.recommended_route is not None
    assert res.recommended_route.mode == "cab"


def test_excluded_cab_never_recommended():
    prefs = preference_profile(PROFILE_FASTEST, excluded_modes=["cab"])
    res = evaluate_routes(_cab_vs_metro_vs_bus(), prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.mode != "cab"
    cab = next(sr for sr in res.ranked_routes if sr.route.mode == "cab")
    assert cab.is_valid is False
    assert "CONSTRAINT_VIOLATION" in cab.reason_codes


def test_max_cost_constraint():
    prefs = UserPreferences(max_cost=50.0)
    res = evaluate_routes(_cab_vs_metro_vs_bus(), prefs)
    for sr in res.ranked_routes:
        if sr.route.cost > 50.0:
            assert sr.is_valid is False
            assert any("EXCEEDS_MAX_COST" in v for v in sr.constraint_violations)
    if res.recommended_route is not None:
        assert res.recommended_route.cost <= 50.0


def test_max_walking_constraint():
    prefs = UserPreferences(max_walking_minutes=5.0)
    res = evaluate_routes(_cab_vs_metro_vs_bus(), prefs)
    metro = next(sr for sr in res.ranked_routes if sr.route.route_id == "metro_cheap")
    assert metro.is_valid is False
    assert any("EXCEEDS_MAX_WALKING" in v for v in metro.constraint_violations)


def test_historical_reliability_affects_ranking():
    stable = RouteCandidate(
        "stable",
        "auto",
        42.0,
        150.0,
        3.0,
        0,
        0.4,
        0.70,
        0.1,
        historical_mobility_signal={
            "has_historical_coverage": True,
            "historical_expected_travel_time_minutes": 41.0,
            "historical_reliability_score": 0.95,
            "confidence_level": "high",
        },
    )
    volatile = RouteCandidate(
        "volatile",
        "cab",
        40.0,
        150.0,
        3.0,
        0,
        0.4,
        0.70,
        0.1,
        historical_mobility_signal={
            "has_historical_coverage": True,
            "historical_expected_travel_time_minutes": 39.0,
            "historical_reliability_score": 0.40,
            "confidence_level": "high",
        },
    )
    res = evaluate_routes([stable, volatile], preference_profile(PROFILE_RELIABLE))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "stable"
    assert effective_reliability(stable) > effective_reliability(volatile)
    assert "HISTORICALLY_STABLE" in next(
        sr.reason_codes for sr in res.ranked_routes if sr.route.route_id == "stable"
    )


def test_missing_historical_coverage_not_penalized():
    with_hist = RouteCandidate(
        "with_hist",
        "auto",
        45.0,
        100.0,
        5.0,
        0,
        0.3,
        0.8,
        0.1,
        historical_mobility_signal={
            "has_historical_coverage": True,
            "historical_expected_travel_time_minutes": 44.0,
            "historical_reliability_score": 0.8,
        },
    )
    no_hist = RouteCandidate(
        "no_hist",
        "bus",
        45.0,
        100.0,
        5.0,
        0,
        0.3,
        0.8,
        0.1,
        historical_mobility_signal={"has_historical_coverage": False},
    )
    res = evaluate_routes([with_hist, no_hist], UserPreferences())
    no_hist_score = next(
        sr.final_score for sr in res.ranked_routes if sr.route.route_id == "no_hist"
    )
    assert all(sr.is_valid for sr in res.ranked_routes)
    assert no_hist_score > 50.0


def test_historical_deviation_contributes_to_reasoning():
    above = RouteCandidate(
        "above_typical",
        "cab",
        50.0,
        200.0,
        1.0,
        0,
        0.5,
        0.7,
        0.1,
        historical_mobility_signal={
            "has_historical_coverage": True,
            "historical_expected_travel_time_minutes": 30.0,
            "historical_reliability_score": 0.7,
        },
    )
    near = RouteCandidate(
        "near_typical",
        "auto",
        31.0,
        200.0,
        1.0,
        0,
        0.5,
        0.7,
        0.1,
        historical_mobility_signal={
            "has_historical_coverage": True,
            "historical_expected_travel_time_minutes": 30.0,
            "historical_reliability_score": 0.7,
        },
    )
    res = evaluate_routes([above, near], UserPreferences())
    above_sr = next(sr for sr in res.ranked_routes if sr.route.route_id == "above_typical")
    near_sr = next(sr for sr in res.ranked_routes if sr.route.route_id == "near_typical")
    assert "CURRENTLY_ABOVE_TYPICAL" in above_sr.reason_codes
    assert "CURRENTLY_NEAR_TYPICAL" in near_sr.reason_codes
    assert near_sr.final_score > above_sr.final_score


def test_reasons_correspond_to_attributes():
    candidates = get_bengaluru_test_candidates()
    res = evaluate_routes(candidates, UserPreferences())
    for sr in res.ranked_routes:
        if "FASTEST" in sr.reason_codes:
            assert sr.route.travel_time_minutes == min(
                c.travel_time_minutes for c in candidates
            )
        if "LOW_COST" in sr.reason_codes:
            assert sr.route.cost == min(c.cost for c in candidates)
        if "LOW_WALKING" in sr.reason_codes:
            assert sr.route.walking_minutes == min(c.walking_minutes for c in candidates)
        if "CONSTRAINT_VIOLATION" in sr.reason_codes:
            assert sr.is_valid is False


def test_alternative_categories_sensible():
    candidates = get_bengaluru_test_candidates()
    res = evaluate_routes(candidates, preference_profile(PROFILE_FASTEST))
    cats = {c.category: c.route.route_id for c in res.route_categories}
    assert CATEGORY_BEST_OVERALL in cats
    assert CATEGORY_FASTEST in cats
    assert CATEGORY_CHEAPEST in cats
    assert CATEGORY_MOST_RELIABLE in cats
    assert cats[CATEGORY_FASTEST] == "bengaluru_cab_express"
    assert cats[CATEGORY_CHEAPEST] == "bengaluru_bmtc_metro_transit"
    assert res.recommended_route is not None
    alts = unique_category_alternatives(
        res.route_categories,
        res.recommended_route.route_id,
    )
    alt_ids = [a.route.route_id for a in alts]
    assert res.recommended_route.route_id not in alt_ids


def test_replan_respects_constraints_and_deterministic_eval():
    routes = _cab_vs_metro_vs_bus()
    prefs = preference_profile(PROFILE_FASTEST, excluded_modes=["cab"])
    evaluation = evaluate_routes(routes, prefs)
    request = CommuteRequest(
        user_id="u1",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        preferences=prefs,
    )
    initial = PlannerResult(
        request=request,
        routes=routes,
        evaluation=evaluation,
        data_sources=["google_maps_routes"],
        historical_signal_used=False,
    )
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        description="traffic spike",
    )
    result = replan_commute(request, initial, change)
    assert result.updated.evaluation is not None
    assert result.updated.evaluation.recommended_route is not None
    assert result.updated.evaluation.recommended_route.mode != "cab"
    cab_sr = next(
        sr for sr in result.updated.evaluation.ranked_routes if sr.route.mode == "cab"
    )
    assert cab_sr.is_valid is False
