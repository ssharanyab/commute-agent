"""
HTTP API tests for the Commute Agent backend.

Maps and Gemini are mocked. No live keys required.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.agent.config import FALLBACK_NOTICE
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.planner.models import CommuteRequest, PlannerResult


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


def _planner_ok() -> PlannerResult:
    routes = [
        _route(),
        _route(
            route_id="maps_drive_1",
            travel_time_minutes=48.0,
            cost=280.0,
            congestion_score=0.30,
        ),
    ]
    prefs = UserPreferences(time_weight=8.0, congestion_weight=5.0, avoid_heavy_traffic=True)
    request = CommuteRequest(
        user_id="api-user",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        departure_time="2030-01-01T08:00:00Z",
        preferences=prefs,
    )
    return PlannerResult(
        request=request,
        routes=routes,
        evaluation=evaluate_routes(routes, prefs),
        data_sources=["google_maps_routes"],
        historical_signal_used=False,
        warnings=[],
    )


def _client() -> TestClient:
    return TestClient(create_app())


def test_health():
    res = _client().get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@patch("src.api.service._invoke_adk_explanation", return_value=("", False, "skipped"))
@patch("src.api.service.plan_commute")
def test_plan_valid(mock_plan, _explain):
    mock_plan.return_value = _planner_ok()
    res = _client().post(
        "/plan",
        json={
            "origin": "Electronic City, Bengaluru",
            "destination": "Koramangala, Bengaluru",
            "departure_time": "2030-01-01T08:00:00Z",
            "objective": "fastest",
            "preferences": {
                "time_weight": 8.0,
                "congestion_weight": 5.0,
                "avoid_heavy_traffic": True,
            },
            "invoke_gemini": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["recommendation"]["route_id"] == "maps_drive_0"
    assert "google_maps_routes" in body["data_sources"]
    assert body["provenance"]["field_policy"]["DRIVE"]["cost"] == "heuristic"
    assert body["gemini"]["invoked"] is False
    assert body["explanation"] == FALLBACK_NOTICE


def test_plan_invalid_missing_origin():
    res = _client().post(
        "/plan",
        json={"destination": "Koramangala, Bengaluru"},
    )
    assert res.status_code == 422


@patch("src.api.service.plan_commute")
@patch("src.api.service.run_adaptive_replan")
def test_replan_valid(mock_replan, mock_plan):
    initial = _planner_ok()
    mock_plan.return_value = initial

    from src.planner.models import ContextChange, ReplanResult
    from dataclasses import replace
    from copy import deepcopy

    routes = deepcopy(initial.routes)
    routes[0] = replace(
        routes[0],
        congestion_score=0.9,
        travel_time_minutes=55.0,
    )
    updated_eval = evaluate_routes(routes, initial.request.preferences)
    updated = PlannerResult(
        request=initial.request,
        routes=routes,
        evaluation=updated_eval,
        data_sources=["google_maps_routes", "simulated_context"],
        warnings=["SIMULATED_CONTEXT_APPLIED (maps_drive_0)"],
    )
    mock_replan.return_value = ReplanResult(
        initial=initial,
        updated=updated,
        context_change=ContextChange(
            traffic_changed=True,
            context_source="simulated",
            target_route_id="maps_drive_0",
            congestion_delta=0.55,
            travel_time_delta_minutes=22.0,
            description="demo",
        ),
        recommendation_changed=True,
        previous_route_id="maps_drive_0",
        new_route_id=updated_eval.recommended_route.route_id,
        provenance_notes=["SIMULATED:demo_context_overlay"],
        explanation="Changed due to simulated traffic.",
        gemini_invoked=True,
        gemini_available=True,
        adk_invoked=True,
        mode="adk_gemini",
    )

    res = _client().post(
        "/replan",
        json={
            "request": {
                "origin": "Electronic City, Bengaluru",
                "destination": "Koramangala, Bengaluru",
                "departure_time": "2030-01-01T08:00:00Z",
                "preferences": {
                    "time_weight": 8.0,
                    "congestion_weight": 5.0,
                    "avoid_heavy_traffic": True,
                },
                "invoke_gemini": True,
            },
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": "maps_drive_0",
                "congestion_delta": 0.55,
                "travel_time_delta_minutes": 22.0,
                "description": "SIMULATED demo traffic spike",
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["recommendation_changed"] is True
    assert body["previous_route_id"] == "maps_drive_0"
    assert body["new_route_id"] == "maps_drive_1"
    assert body["context_change"]["context_source"] == "simulated"
    assert body["gemini"]["invoked"] is True
    assert "before" in body and "after" in body


def test_replan_invalid_context_source():
    res = _client().post(
        "/replan",
        json={
            "request": {
                "origin": "Electronic City, Bengaluru",
                "destination": "Koramangala, Bengaluru",
            },
            "context_change": {"context_source": "bogus"},
        },
    )
    assert res.status_code == 422


@patch("src.api.service._invoke_adk_explanation", return_value=("", False, "skipped"))
@patch("src.api.service.plan_commute")
def test_plan_maps_failure_no_fabricated_routes(mock_plan, _explain):
    request = CommuteRequest(
        user_id="api-user",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
    )
    mock_plan.return_value = PlannerResult(
        request=request,
        routes=[],
        evaluation=None,
        data_sources=[],
        error="MAPS_API_UNAVAILABLE",
        error_detail="GOOGLE_MAPS_API_KEY environment variable is not set.",
        warnings=[],
    )
    res = _client().post(
        "/plan",
        json={
            "origin": "Electronic City, Bengaluru",
            "destination": "Koramangala, Bengaluru",
            "invoke_gemini": False,
        },
    )
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "MAPS_API_UNAVAILABLE"
    assert body["recommendation"] is None
    assert body["routes"] == []


@patch("src.api.service.gemini_credentials_available", return_value=True)
@patch("src.api.service.adk_importable", return_value=True)
@patch("src.api.service._invoke_adk_explanation")
@patch("src.api.service.plan_commute")
def test_plan_gemini_failure_uses_deterministic_fallback(
    mock_plan, mock_explain, _adk, _creds
):
    mock_plan.return_value = _planner_ok()
    mock_explain.return_value = ("", False, "ADK execution failed: no events returned")
    res = _client().post(
        "/plan",
        json={
            "origin": "Electronic City, Bengaluru",
            "destination": "Koramangala, Bengaluru",
            "invoke_gemini": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation"]["route_id"] == "maps_drive_0"
    assert body["gemini"]["invoked"] is False
    assert body["gemini"]["mode"] == "deterministic_fallback"
    assert body["explanation"] == FALLBACK_NOTICE
    assert any("ADK execution failed" in w for w in body["warnings"])


@patch("src.api.service.plan_commute")
def test_replan_maps_failure_no_fabricated_results(mock_plan):
    request = CommuteRequest(
        user_id="api-user",
        origin="A",
        destination="B",
    )
    mock_plan.return_value = PlannerResult(
        request=request,
        routes=[],
        evaluation=None,
        error="MAPS_API_UNAVAILABLE",
        error_detail="auth failed",
    )
    res = _client().post(
        "/replan",
        json={
            "request": {"origin": "A", "destination": "B", "invoke_gemini": False},
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": "maps_drive_0",
                "congestion_delta": 0.5,
            },
        },
    )
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["previous_recommendation"] is None
    assert body["new_recommendation"] is None
    assert body["gemini"]["invoked"] is False
