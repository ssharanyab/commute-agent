"""
HTTP API tests for the Commute Agent backend.

Maps and Gemini are mocked. Planning path is ADK Mobility Orchestrator.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.agent.capabilities import DecisionCapabilityResult, OrchestrationMetadata
from src.agent.config import FALLBACK_NOTICE
from src.agent.orchestrator import OrchestrationResult
from src.agent.schemas import AgentRecommendation
from src.api.app import create_app
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.planner.models import CommuteRequest, ContextChange, PlannerResult, ReplanResult


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
        cost_status="known",
        duration_status="known",
        component_modes=["cab"],
        mode_signature="cab",
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def _orch_ok(*, gemini_invoked: bool = False, mode: str = "deterministic_fallback") -> OrchestrationResult:
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
    evaluation = evaluate_routes(routes, prefs)
    rec_route = evaluation.recommended_route
    recommendation = AgentRecommendation(
        recommended_route=rec_route,
        alternatives=[r for r in routes if r.route_id != rec_route.route_id],
        estimated_time=rec_route.travel_time_minutes if rec_route else None,
        estimated_cost=rec_route.cost if rec_route else None,
        walking_time=rec_route.walking_minutes if rec_route else None,
        transfers=rec_route.transfers if rec_route else None,
        reliability=rec_route.reliability_score if rec_route else None,
        traffic=rec_route.congestion_score if rec_route else None,
        explanation=FALLBACK_NOTICE,
        reason_codes=list(evaluation.reason_codes),
        data_sources=["journey_builder", "decision_engine"],
        historical_signal_used=False,
        replanning_available=True,
        warnings=[],
        error=None,
    )
    decision = DecisionCapabilityResult(
        ranked_route_ids=[s.route.route_id for s in evaluation.ranked_routes if s.is_valid],
        recommended_route_id=rec_route.route_id if rec_route else None,
        category_assignments={
            c.category: c.route.route_id for c in evaluation.route_categories
        },
        scores={s.route.route_id: s.final_score for s in evaluation.ranked_routes if s.is_valid},
        reason_codes=list(evaluation.reason_codes),
        evaluation=evaluation.to_dict() if hasattr(evaluation, "to_dict") else {},
    )
    meta = OrchestrationMetadata(
        capabilities=[],
        network_snapshot_versions={"bmtc": "test"},
        warnings=[],
    )
    return OrchestrationResult(
        recommendation=recommendation,
        journey_build=None,
        journeys=[],
        route_candidates=routes,
        evaluation=evaluation,
        decision=decision,
        mobility_context=None,
        personalization=None,
        historical=None,
        weather=None,
        enrichment_results={},
        metadata=meta,
        gemini_available=False,
        gemini_invoked=gemini_invoked,
        adk_invoked=gemini_invoked,
        mode=mode,
    )


def _orch_maps_fail() -> OrchestrationResult:
    recommendation = AgentRecommendation(
        recommended_route=None,
        alternatives=[],
        estimated_time=None,
        estimated_cost=None,
        walking_time=None,
        transfers=None,
        reliability=None,
        traffic=None,
        explanation=FALLBACK_NOTICE,
        reason_codes=[],
        data_sources=[],
        historical_signal_used=False,
        replanning_available=False,
        warnings=[],
        error="MAPS_API_UNAVAILABLE",
    )
    return OrchestrationResult(
        recommendation=recommendation,
        journey_build=None,
        journeys=[],
        route_candidates=[],
        evaluation=None,
        decision=None,
        mobility_context=None,
        personalization=None,
        historical=None,
        weather=None,
        enrichment_results={},
        metadata=OrchestrationMetadata(),
        mode="deterministic_fallback",
    )


def _client() -> TestClient:
    return TestClient(create_app())


def test_health():
    res = _client().get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@patch("src.api.service.plan_commute_with_adk")
def test_plan_valid(mock_orch):
    mock_orch.return_value = _orch_ok()
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
            "invoke_live_traffic": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["orchestration"] == "adk_mobility_orchestrator"
    assert body["recommendation"]["route_id"] == "maps_drive_0"
    assert "decision_engine" in body["data_sources"] or "journey_builder" in body["data_sources"]
    assert body["provenance"]["field_policy"]["DRIVE"]["cost"] == "heuristic"
    assert body["gemini"]["invoked"] is False
    assert body["explanation"] == FALLBACK_NOTICE
    mock_orch.assert_called_once()


def test_plan_invalid_missing_origin():
    res = _client().post(
        "/plan",
        json={"destination": "Koramangala, Bengaluru"},
    )
    assert res.status_code == 422


@patch("src.api.service.plan_commute_with_adk")
@patch("src.api.service.run_adaptive_replan_from_snapshot")
@patch("src.api.service.snapshot_from_orchestration")
def test_replan_valid(mock_snap, mock_replan, mock_orch):
    from copy import deepcopy
    from dataclasses import replace

    from src.agent.adaptive import PlanSnapshot
    from datetime import datetime, timezone

    orch = _orch_ok()
    mock_orch.return_value = orch

    initial = PlannerResult(
        request=CommuteRequest(
            user_id="api-user",
            origin="Electronic City, Bengaluru",
            destination="Koramangala, Bengaluru",
            preferences=UserPreferences(time_weight=8.0, congestion_weight=5.0),
        ),
        routes=list(orch.route_candidates),
        evaluation=orch.evaluation,
        data_sources=["journey_builder", "decision_engine"],
    )
    snap = PlanSnapshot(
        plan_id="plan-test",
        timestamp=datetime.now(timezone.utc),
        request=initial.request,
        selected_journey_id="maps_drive_0",
        candidate_ids=[r.route_id for r in initial.routes],
        routes=list(initial.routes),
        scores={"maps_drive_0": 10.0, "maps_drive_1": 20.0},
        evaluation=initial.evaluation,
        planner_result=initial,
    )
    mock_snap.return_value = snap

    routes = deepcopy(initial.routes)
    routes[0] = replace(routes[0], congestion_score=0.9, travel_time_minutes=55.0)
    updated_eval = evaluate_routes(routes, initial.request.preferences)
    updated = PlannerResult(
        request=initial.request,
        routes=routes,
        evaluation=updated_eval,
        data_sources=["journey_builder", "decision_engine", "simulated_context"],
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
                "invoke_live_traffic": False,
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
    assert body["orchestration"] == "adk_adaptive_replan"
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


@patch("src.api.service.plan_commute_with_adk")
def test_plan_maps_failure_no_fabricated_routes(mock_orch):
    mock_orch.return_value = _orch_maps_fail()
    res = _client().post(
        "/plan",
        json={
            "origin": "Electronic City, Bengaluru",
            "destination": "Koramangala, Bengaluru",
            "invoke_gemini": False,
            "invoke_live_traffic": False,
        },
    )
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "MAPS_API_UNAVAILABLE"
    assert body["recommendation"] is None
    assert body["routes"] == []


@patch("src.api.service.plan_commute_with_adk")
def test_plan_gemini_failure_uses_deterministic_fallback(mock_orch):
    orch = _orch_ok(gemini_invoked=False, mode="deterministic_fallback")
    orch.recommendation.warnings.append("ADK execution failed: no events returned")
    orch.gemini_available = True
    mock_orch.return_value = orch
    res = _client().post(
        "/plan",
        json={
            "origin": "Electronic City, Bengaluru",
            "destination": "Koramangala, Bengaluru",
            "invoke_gemini": True,
            "invoke_live_traffic": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation"]["route_id"] == "maps_drive_0"
    assert body["gemini"]["invoked"] is False
    assert body["gemini"]["mode"] == "deterministic_fallback"
    assert body["explanation"] == FALLBACK_NOTICE
    assert any("ADK execution failed" in w for w in body["warnings"])


@patch("src.api.service.plan_commute_with_adk")
def test_replan_maps_failure_no_fabricated_results(mock_orch):
    mock_orch.return_value = _orch_maps_fail()
    res = _client().post(
        "/replan",
        json={
            "request": {
                "origin": "A",
                "destination": "B",
                "invoke_gemini": False,
                "invoke_live_traffic": False,
            },
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
