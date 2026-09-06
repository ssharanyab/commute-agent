"""
Unit tests for Route Evaluation Engine scoring, constraint handling, and ranking.
"""

import pytest
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from tests.fixtures import get_bengaluru_test_candidates


def test_fastest_route_wins_for_time_heavy_preferences():
    """Test 1: Fastest route (cab_express, 32 min) wins when time weight is heavily prioritized."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(
        time_weight=10.0,
        cost_weight=0.1,
        walking_weight=0.1,
        transfer_weight=0.1,
        congestion_weight=0.1,
        reliability_weight=0.1
    )
    res = evaluate_routes(candidates, prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "bengaluru_cab_express"
    assert "FASTEST" in res.reason_codes


def test_cheapest_route_wins_for_cost_heavy_preferences():
    """Test 2: Cheapest route (metro_transit, ₹45) wins when cost weight is heavily prioritized."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(
        time_weight=0.1,
        cost_weight=10.0,
        walking_weight=0.1,
        transfer_weight=0.1,
        congestion_weight=0.1,
        reliability_weight=0.1
    )
    res = evaluate_routes(candidates, prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "bengaluru_bmtc_metro_transit"
    assert "LOW_COST" in res.reason_codes


def test_low_walking_route_wins_for_walking_sensitive_preferences():
    """Test 3: Low-walking route wins when walking weight is heavily penalized."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(
        time_weight=0.1,
        cost_weight=0.1,
        walking_weight=10.0,
        transfer_weight=0.1,
        congestion_weight=0.1,
        reliability_weight=0.1
    )
    res = evaluate_routes(candidates, prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "bengaluru_cab_express"
    assert "LOW_WALKING" in res.reason_codes


def test_fewer_transfer_route_wins_for_transfer_sensitive_preferences():
    """Test 4: Fewer-transfer route wins when transfers are heavily penalized."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(
        time_weight=0.1,
        cost_weight=0.1,
        walking_weight=0.1,
        transfer_weight=10.0,
        congestion_weight=0.1,
        reliability_weight=0.1
    )
    res = evaluate_routes(candidates, prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id in ["bengaluru_cab_express", "bengaluru_auto_arterial"]
    assert "FEWER_TRANSFERS" in res.reason_codes


def test_heavy_congestion_route_is_penalized():
    """Test 5: Congested route (cab_express, congestion 0.75) is penalized when congestion weight is high."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(
        time_weight=1.0,
        cost_weight=1.0,
        congestion_weight=10.0
    )
    res = evaluate_routes(candidates, prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id != "bengaluru_cab_express"


def test_unreliable_disrupted_route_is_penalized():
    """Test 6: Unreliable or disrupted route is penalized when reliability weight is high."""
    c1 = RouteCandidate("r1", "cab", 30.0, 100.0, 2.0, 0, 0.2, 0.40, 0.80)  # Unreliable
    c2 = RouteCandidate("r2", "auto", 35.0, 100.0, 2.0, 0, 0.2, 0.95, 0.05) # Reliable
    
    prefs = UserPreferences(reliability_weight=10.0)
    res = evaluate_routes([c1, c2], prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "r2"


def test_max_walking_constraint_excludes_route():
    """Test 7: max_walking_minutes constraint invalidates route exceeding threshold."""
    candidates = get_bengaluru_test_candidates() # metro_transit has 9 min walking
    prefs = UserPreferences(max_walking_minutes=5.0)
    res = evaluate_routes(candidates, prefs)
    
    metro_scored = next(r for r in res.ranked_routes if r.route.route_id == "bengaluru_bmtc_metro_transit")
    assert metro_scored.is_valid is False
    assert any("EXCEEDS_MAX_WALKING" in v for v in metro_scored.constraint_violations)


def test_max_cost_constraint_excludes_route():
    """Test 8: max_cost constraint invalidates route exceeding budget."""
    candidates = get_bengaluru_test_candidates() # cab_express costs ₹350
    prefs = UserPreferences(max_cost=200.0)
    res = evaluate_routes(candidates, prefs)
    
    cab_scored = next(r for r in res.ranked_routes if r.route.route_id == "bengaluru_cab_express")
    assert cab_scored.is_valid is False
    assert any("EXCEEDS_MAX_COST" in v for v in cab_scored.constraint_violations)


def test_preferred_mode_affects_ranking():
    """Test 9: Setting preferred_modes boosts the preferred transit mode."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(preferred_modes=["metro"], time_weight=1.0, cost_weight=1.0)
    res = evaluate_routes(candidates, prefs)
    
    metro_scored = next(r for r in res.ranked_routes if r.route.route_id == "bengaluru_bmtc_metro_transit")
    assert "PREFERRED_MODE" in metro_scored.reason_codes
    assert metro_scored.sub_scores["bonus_preferred"] == 10.0


def test_historical_signal_modifies_scoring_when_available():
    """Test 10: Candidate with historical ML coverage gets bonus/reason code."""
    candidates = get_bengaluru_test_candidates()
    res = evaluate_routes(candidates, UserPreferences())
    
    auto_scored = next(r for r in res.ranked_routes if r.route.route_id == "bengaluru_auto_arterial")
    assert "HISTORICAL_SUPPORT" in auto_scored.reason_codes


def test_missing_historical_signal_falls_back_safely():
    """Test 11: Candidate without historical coverage evaluates safely without error or invalidation."""
    c_no_hist = RouteCandidate(
        route_id="custom_route",
        mode="bus",
        travel_time_minutes=40.0,
        cost=30.0,
        walking_minutes=5.0,
        transfers=0,
        congestion_score=0.3,
        reliability_score=0.8,
        disruption_risk=0.1,
        historical_mobility_signal=None
    )
    res = evaluate_routes([c_no_hist], UserPreferences())
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "custom_route"
    assert res.ranked_routes[0].is_valid is True


def test_identical_inputs_produce_deterministic_results():
    """Test 12: Evaluating identical candidates multiple times yields exact same scores and ranking."""
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(time_weight=2.0, cost_weight=1.5)
    
    res1 = evaluate_routes(candidates, prefs)
    res2 = evaluate_routes(candidates, prefs)
    
    assert res1.to_dict() == res2.to_dict()
