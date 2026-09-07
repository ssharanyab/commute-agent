"""
Tests for adaptive replanning.

Gemini/ADK calls are mocked. No live API key required.
"""

from unittest.mock import patch

import pytest

from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.planner.models import (
    CommuteRequest,
    ContextChange,
    InvalidReplanInput,
    PlannerResult,
)
from src.planner.replan import replan_commute
from src.agent.replan import run_adaptive_replan
from src.agent.config import FALLBACK_NOTICE
from src.agent.planner import MODE_ADK_GEMINI, MODE_DETERMINISTIC_FALLBACK


def _route(**overrides) -> RouteCandidate:
    defaults = dict(
        route_id="maps_drive_0",
        mode="cab",
        travel_time_minutes=28.0,
        cost=320.0,
        walking_minutes=0.0,
        transfers=0,
        congestion_score=0.25,
        reliability_score=0.85,
        disruption_risk=0.10,
        historical_mobility_signal=None,
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def _alt() -> RouteCandidate:
    return _route(
        route_id="maps_drive_1",
        travel_time_minutes=48.0,
        cost=280.0,
        congestion_score=0.30,
        walking_minutes=0.0,
    )


def _request(**overrides) -> CommuteRequest:
    defaults = dict(
        user_id="user-1",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        departure_time="2030-01-01T08:00:00Z",
        preferences=UserPreferences(
            time_weight=8.0,
            cost_weight=1.0,
            congestion_weight=5.0,
            avoid_heavy_traffic=True,
        ),
    )
    defaults.update(overrides)
    return CommuteRequest(**defaults)


def _initial_result(routes=None, prefs=None) -> PlannerResult:
    routes = routes or [_route(), _alt()]
    prefs = prefs or _request().preferences
    evaluation = evaluate_routes(routes, prefs)
    return PlannerResult(
        request=_request(preferences=prefs),
        routes=routes,
        evaluation=evaluation,
        data_sources=["google_maps_routes"],
        historical_signal_used=False,
        warnings=[],
    )


def test_initial_recommendation():
    initial = _initial_result()
    assert initial.evaluation is not None
    assert initial.evaluation.recommended_route is not None
    assert initial.evaluation.recommended_route.route_id == "maps_drive_0"


def test_replan_unchanged_context():
    initial = _initial_result()
    change = ContextChange(context_source="none", description="no change")
    result = replan_commute(initial.request, initial, change)
    assert result.recommendation_changed is False
    assert result.previous_route_id == result.new_route_id
    assert "CONTEXT_UNCHANGED" in result.updated.warnings
    assert any("UNCHANGED_CONTEXT" in p for p in result.provenance_notes)


def test_replan_after_traffic_change_can_switch_route():
    initial = _initial_result()
    before = initial.evaluation.recommended_route.route_id
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id=before,
        congestion_delta=0.55,
        travel_time_delta_minutes=25.0,
        description="Simulated heavy traffic on previously recommended route",
    )
    result = replan_commute(initial.request, initial, change)
    assert result.recommendation_changed is True
    assert result.previous_route_id == before
    assert result.new_route_id != before
    assert result.new_route_id == "maps_drive_1"
    assert any("SIMULATED:" in p for p in result.provenance_notes)
    assert "simulated_context" in result.updated.data_sources


def test_recommendation_change_flag():
    initial = _initial_result()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="maps_drive_0",
        congestion_delta=0.6,
        travel_time_delta_minutes=30.0,
        description="demo traffic spike",
    )
    result = replan_commute(initial.request, initial, change)
    assert result.recommendation_changed is True


def test_deterministic_evaluator_remains_authority():
    """Replan ranking must match a direct evaluate_routes call on overlaid routes."""
    initial = _initial_result()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="maps_drive_0",
        congestion_delta=0.6,
        travel_time_delta_minutes=30.0,
        description="demo",
    )
    result = replan_commute(initial.request, initial, change)
    # Manual overlay + evaluate must agree with replan recommendation
    from copy import deepcopy
    from dataclasses import replace

    routes = deepcopy(initial.routes)
    routes = [
        replace(
            r,
            congestion_score=min(1.0, r.congestion_score + 0.6),
            travel_time_minutes=r.travel_time_minutes + 30.0,
        )
        if r.route_id == "maps_drive_0"
        else r
        for r in routes
    ]
    direct = evaluate_routes(routes, initial.request.preferences)
    assert direct.recommended_route.route_id == result.new_route_id
    assert result.updated.evaluation.recommended_route.route_id == direct.recommended_route.route_id


@patch("src.agent.replan._invoke_replan_explanation")
@patch("src.agent.replan.gemini_credentials_available", return_value=True)
@patch("src.agent.replan.adk_importable", return_value=True)
def test_gemini_explanation_on_replan(_adk, _creds, mock_explain):
    initial = _initial_result()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="maps_drive_0",
        congestion_delta=0.6,
        travel_time_delta_minutes=30.0,
        description="demo traffic",
    )
    mock_explain.return_value = (
        "The recommendation changed from maps_drive_0 to maps_drive_1 because "
        "simulated traffic increased on maps_drive_0.",
        True,
        "",
    )
    result = run_adaptive_replan(initial.request, initial, change, invoke_gemini=True)
    assert result.mode == MODE_ADK_GEMINI
    assert result.gemini_invoked is True
    assert "maps_drive_0" in result.explanation
    assert result.recommendation_changed is True


@patch("src.agent.replan._invoke_replan_explanation")
@patch("src.agent.replan.gemini_credentials_available", return_value=True)
@patch("src.agent.replan.adk_importable", return_value=True)
def test_gemini_fallback_still_returns_deterministic_replan(_adk, _creds, mock_explain):
    initial = _initial_result()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="maps_drive_0",
        congestion_delta=0.6,
        travel_time_delta_minutes=30.0,
        description="demo",
    )
    mock_explain.return_value = ("", False, "ADK execution failed: no events returned")
    result = run_adaptive_replan(initial.request, initial, change, invoke_gemini=True)
    assert result.mode == MODE_DETERMINISTIC_FALLBACK
    assert result.gemini_invoked is False
    assert result.explanation == FALLBACK_NOTICE
    assert result.recommendation_changed is True
    assert result.new_route_id == "maps_drive_1"


def test_malformed_replan_input_raises():
    initial = _initial_result()
    with pytest.raises(InvalidReplanInput):
        replan_commute(initial.request, initial, None)
    with pytest.raises(InvalidReplanInput):
        replan_commute(
            initial.request,
            initial,
            ContextChange(context_source="bogus"),
        )
    failed = PlannerResult(
        request=initial.request,
        routes=[],
        evaluation=None,
        error="NO_ROUTES",
    )
    with pytest.raises(InvalidReplanInput):
        replan_commute(
            initial.request,
            failed,
            ContextChange(context_source="none"),
        )


def test_gemini_cannot_override_replan_route_ids():
    """Explanation text does not alter deterministic new_route_id."""
    initial = _initial_result()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="maps_drive_0",
        congestion_delta=0.6,
        travel_time_delta_minutes=30.0,
        description="demo",
    )
    with patch("src.agent.replan._invoke_replan_explanation") as mock_explain:
        mock_explain.return_value = (
            "I recommend inventing route maps_drive_999 instead.",
            True,
            "",
        )
        with patch("src.agent.replan.gemini_credentials_available", return_value=True):
            with patch("src.agent.replan.adk_importable", return_value=True):
                result = run_adaptive_replan(
                    initial.request, initial, change, invoke_gemini=True
                )
    assert result.new_route_id == "maps_drive_1"
    assert result.new_route_id != "maps_drive_999"
