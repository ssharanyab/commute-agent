"""Regression tests: hard excluded_modes (e.g. no cabs) are deterministic."""

from src.agent.schemas import ground_recommendation, recommendation_from_planner
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.scoring import mode_is_excluded, validate_hard_constraints
from src.planner.models import CommuteRequest, PlannerResult
from tests.fixtures import get_bengaluru_test_candidates


def _cab_metro_auto():
    return [
        RouteCandidate("drive_cab", "cab", 30.0, 300.0, 1.0, 0, 0.3, 0.9, 0.1),
        RouteCandidate("metro_1", "metro", 55.0, 45.0, 8.0, 1, 0.2, 0.85, 0.1),
        RouteCandidate("auto_1", "auto", 40.0, 150.0, 3.0, 0, 0.35, 0.8, 0.15),
    ]


def test_no_cabs_marks_cab_invalid():
    prefs = UserPreferences(excluded_modes=["cab"], time_weight=10.0)
    cab = _cab_metro_auto()[0]
    violations = validate_hard_constraints(cab, prefs)
    assert any("EXCLUDED_MODE" in v for v in violations)
    assert mode_is_excluded("cab", ["cab"])
    assert mode_is_excluded("taxi", ["cab"])
    assert mode_is_excluded("drive", ["cab"])


def test_avoid_cabs_phrase_equivalent_via_excluded_modes():
    """API/Flutter map 'Avoid cabs' → excluded_modes=['cab']."""
    prefs = UserPreferences(excluded_modes=["cab"])
    res = evaluate_routes(_cab_metro_auto(), prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.mode != "cab"
    cab_scored = next(r for r in res.ranked_routes if r.route.mode == "cab")
    assert cab_scored.is_valid is False


def test_excluded_cab_valid_metro_can_win():
    prefs = UserPreferences(excluded_modes=["cab"], time_weight=10.0)
    res = evaluate_routes(_cab_metro_auto(), prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.route_id in {"metro_1", "auto_1"}
    assert res.recommended_route.mode != "cab"


def test_all_non_cab_invalid_returns_no_recommendation_not_cab():
    routes = [
        RouteCandidate("drive_cab", "cab", 20.0, 200.0, 0.0, 0, 0.1, 0.9, 0.05),
        RouteCandidate("metro_far", "metro", 80.0, 40.0, 25.0, 2, 0.2, 0.8, 0.1),
    ]
    prefs = UserPreferences(
        excluded_modes=["cab"],
        max_walking_minutes=5.0,  # invalidates metro
    )
    res = evaluate_routes(routes, prefs)
    assert res.recommended_route is None
    assert "NO_VALID_ROUTE" in res.reason_codes
    cab_scored = next(r for r in res.ranked_routes if r.route.mode == "cab")
    assert cab_scored.is_valid is False


def test_max_walking_constraint_still_works():
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(max_walking_minutes=5.0)
    res = evaluate_routes(candidates, prefs)
    metro_scored = next(
        r for r in res.ranked_routes if r.route.route_id == "bengaluru_bmtc_metro_transit"
    )
    assert metro_scored.is_valid is False
    assert any("EXCEEDS_MAX_WALKING" in v for v in metro_scored.constraint_violations)


def test_max_cost_constraint_still_works():
    candidates = get_bengaluru_test_candidates()
    prefs = UserPreferences(max_cost=200.0)
    res = evaluate_routes(candidates, prefs)
    cab_scored = next(
        r for r in res.ranked_routes if r.route.route_id == "bengaluru_cab_express"
    )
    assert cab_scored.is_valid is False
    assert any("EXCEEDS_MAX_COST" in v for v in cab_scored.constraint_violations)


def test_gemini_cannot_override_excluded_mode():
    prefs = UserPreferences(excluded_modes=["cab"])
    evaluation = evaluate_routes(_cab_metro_auto(), prefs)
    assert evaluation.recommended_route is not None
    assert evaluation.recommended_route.mode != "cab"

    planner = PlannerResult(
        request=CommuteRequest(
            user_id="t",
            origin="A",
            destination="B",
            preferences=prefs,
        ),
        routes=_cab_metro_auto(),
        evaluation=evaluation,
        data_sources=["google_maps_routes"],
    )
    grounded = ground_recommendation(
        planner,
        explanation="cab is best",
        conflicting={
            "recommended_route_id": "drive_cab",
            "route_id": "drive_cab",
            "estimated_time": 1.0,
        },
    )
    assert grounded.recommended_route is not None
    assert grounded.recommended_route.route_id != "drive_cab"
    assert grounded.recommended_route.mode != "cab"
    assert any("discarded conflicting" in w for w in grounded.warnings)


def test_without_exclusion_cab_can_still_win():
    prefs = UserPreferences(time_weight=10.0, cost_weight=0.1)
    res = evaluate_routes(_cab_metro_auto(), prefs)
    assert res.recommended_route is not None
    assert res.recommended_route.mode == "cab"


def test_replan_preserves_exclusion_on_request_preferences():
    """Replan uses CommuteRequest.preferences; excluded_modes must stick."""
    from src.planner.replan import replan_commute
    from src.planner.models import ContextChange
    from copy import deepcopy
    from dataclasses import replace

    prefs = UserPreferences(excluded_modes=["cab"], time_weight=5.0)
    routes = _cab_metro_auto()
    initial_eval = evaluate_routes(routes, prefs)
    assert initial_eval.recommended_route is not None
    assert initial_eval.recommended_route.mode != "cab"

    request = CommuteRequest(
        user_id="t",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        preferences=prefs,
    )
    initial = PlannerResult(
        request=request,
        routes=routes,
        evaluation=initial_eval,
        data_sources=["google_maps_routes"],
    )
    # Simulate traffic spike on current recommendation — still must not pick cab.
    updated_routes = deepcopy(routes)
    for i, r in enumerate(updated_routes):
        if r.route_id == initial_eval.recommended_route.route_id:
            updated_routes[i] = replace(
                r,
                congestion_score=0.95,
                travel_time_minutes=r.travel_time_minutes + 40,
            )

    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id=initial_eval.recommended_route.route_id,
        congestion_delta=0.5,
        travel_time_delta_minutes=40.0,
        description="spike",
    )
    # replan_commute applies overlay then re-evaluates with request.preferences
    result = replan_commute(
        request,
        initial,
        change,
        refresh_live_routes=False,
    )
    assert result.updated.evaluation is not None
    rec = result.updated.evaluation.recommended_route
    if rec is not None:
        assert rec.mode != "cab"
    cab = next(r for r in result.updated.evaluation.ranked_routes if r.route.mode == "cab")
    assert cab.is_valid is False
