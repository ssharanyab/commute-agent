"""Phase 7E — /replan returns Top-5 from the same DE pipeline as /plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.api import service as api_service
from src.api.app import create_app
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, UserPreferences, preference_profile
from src.decision_engine.models import PROFILE_FASTEST
from src.network.file_repository import FileStaticMobilityRepository
from src.planner.models import CommuteRequest, ContextChange, PlannerResult
from src.planner.replan import replan_commute
from tests.test_orchestrator_phase5d import _publish_corridor


@pytest.fixture
def demo_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish_corridor(repo)
    return repo


@pytest.fixture
def client(demo_repo):
    api_service.set_mobility_repository(demo_repo)
    try:
        yield TestClient(create_app())
    finally:
        api_service.set_mobility_repository(None)


def _plan_body(**overrides):
    body = {
        "origin": ELECTRONIC_CITY.address,
        "destination": MAJESTIC.address,
        "origin_lat": ELECTRONIC_CITY.latitude,
        "origin_lon": ELECTRONIC_CITY.longitude,
        "destination_lat": MAJESTIC.latitude,
        "destination_lon": MAJESTIC.longitude,
        "departure_time": "2030-01-15T08:00:00Z",
        "invoke_gemini": False,
        "invoke_live_traffic": False,
        "invoke_weather": False,
        "invoke_historical": False,
        "allow_legacy_maps_fallback": False,
    }
    body.update(overrides)
    return body


def _assert_top5_contract(body: dict) -> None:
    assert "recommendation" in body
    assert "top_journeys" in body
    assert "top_selection" in body
    top = body["top_selection"]
    assert isinstance(top, dict)
    assert top.get("max_count") == 5
    journeys = body["top_journeys"] or []
    sel_journeys = top.get("top_journeys") or []
    assert journeys == sel_journeys
    assert top.get("selected_count") == len(journeys)
    assert len(journeys) <= 5


def test_replan_http_200_includes_top5(client):
    plan = client.post("/plan", json=_plan_body()).json()
    assert plan["ok"] is True
    route_id = plan["decision"]["recommended_route_id"]

    res = client.post(
        "/replan",
        json={
            "request": _plan_body(),
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": route_id,
                "congestion_delta": 0.6,
                "travel_time_delta_minutes": 35.0,
                "description": "SIMULATED traffic spike",
            },
            "refresh_live_routes": False,
            "invoke_gemini": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    _assert_top5_contract(body)
    assert body["recommendation"] is not None
    assert body["new_recommendation"] is not None
    assert body["recommendation"]["route_id"] == body["new_recommendation"]["route_id"]


def test_replan_recommendation_matches_top5_first(client):
    plan = client.post("/plan", json=_plan_body()).json()
    route_id = plan["decision"]["recommended_route_id"]
    body = client.post(
        "/replan",
        json={
            "request": _plan_body(),
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": route_id,
                "congestion_delta": 0.55,
                "travel_time_delta_minutes": 22.0,
            },
            "refresh_live_routes": False,
            "invoke_gemini": False,
        },
    ).json()

    rec_id = body["recommendation"]["route_id"]
    top = body["top_selection"]
    assert top["recommended"]["route_id"] == rec_id
    assert body["top_journeys"][0]["route_id"] == rec_id
    assert body["top_journeys"][0]["is_recommended"] is True
    assert top["recommended"]["is_recommended"] is True


def test_replan_refreshes_winner_not_pinned_to_old(client):
    plan = client.post("/plan", json=_plan_body(preference_profile="FASTEST")).json()
    old_id = plan["decision"]["recommended_route_id"]
    assert old_id
    assert plan.get("top_journeys")

    body = client.post(
        "/replan",
        json={
            "request": _plan_body(preference_profile="FASTEST"),
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": old_id,
                "congestion_delta": 0.9,
                "travel_time_delta_minutes": 80.0,
                "description": "severe simulated delay on previous winner",
            },
            "refresh_live_routes": False,
            "invoke_gemini": False,
        },
    ).json()

    assert body["ok"] is True
    new_id = body["recommendation"]["route_id"]
    assert body["top_journeys"][0]["route_id"] == new_id
    # If switch occurred, old must not remain first merely by prior recommendation.
    if body.get("recommendation_changed"):
        assert new_id != old_id
        assert body["top_journeys"][0]["route_id"] != old_id


def test_replan_preserves_request_strategy_and_constraints(client):
    """Request with strategy/constraints still yields a valid Top-5 replan payload."""
    plan_body = _plan_body(
        preference_profile="BALANCED",
        strategy="PUBLIC_TRANSPORT_FIRST",
        constraints={
            "excluded_modes": ["cab"],
            "max_walking_distance_meters": 2000,
            "max_transfers": 3,
            "allowed_accessory_modes": ["walk", "auto"],
        },
    )
    plan = client.post("/plan", json=plan_body).json()
    assert plan["ok"] is True
    route_id = plan["decision"]["recommended_route_id"]

    body = client.post(
        "/replan",
        json={
            "request": plan_body,
            "context_change": {
                "traffic_changed": True,
                "context_source": "simulated",
                "target_route_id": route_id,
                "congestion_delta": 0.4,
                "travel_time_delta_minutes": 15.0,
            },
            "refresh_live_routes": False,
            "invoke_gemini": False,
        },
    ).json()
    assert body["ok"] is True
    _assert_top5_contract(body)
    assert body.get("initial_request") is not None
    assert body["recommendation"] is not None
    assert body["top_journeys"][0]["is_recommended"] is True

def _route(**overrides) -> RouteCandidate:
    defaults = dict(
        route_id="a",
        mode="cab",
        travel_time_minutes=30.0,
        cost=300.0,
        walking_minutes=0.0,
        transfers=0,
        congestion_score=0.2,
        reliability_score=0.8,
        disruption_risk=0.1,
        component_modes=["cab"],
        cost_status="known",
        duration_status="known",
        walking_distance_meters=0.0,
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def test_replan_commute_evaluation_carries_top_selection():
    prefs = preference_profile(PROFILE_FASTEST)
    routes = [
        _route(route_id="fast", travel_time_minutes=25, component_modes=["cab"]),
        _route(
            route_id="bus",
            mode="bus",
            travel_time_minutes=45,
            cost=25,
            component_modes=["walk", "bus", "walk"],
            walking_distance_meters=400,
            walking_minutes=5,
        ),
        _route(
            route_id="metro",
            mode="metro",
            travel_time_minutes=40,
            cost=40,
            component_modes=["walk", "metro", "walk"],
            walking_distance_meters=600,
            walking_minutes=8,
        ),
    ]
    initial_eval = evaluate_routes(routes, prefs)
    initial = PlannerResult(
        request=CommuteRequest(
            user_id="u",
            origin="A",
            destination="B",
            preferences=prefs,
        ),
        routes=routes,
        evaluation=initial_eval,
        data_sources=["test"],
        historical_signal_used=False,
    )
    assert initial_eval.top_selection
    old_rec = initial_eval.recommended_route.route_id

    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            traffic_changed=True,
            context_source="simulated",
            target_route_id=old_rec,
            congestion_delta=0.8,
            travel_time_delta_minutes=50.0,
        ),
    )
    assert result.updated.evaluation is not None
    top = result.updated.evaluation.top_selection
    assert top is not None
    assert top["max_count"] == 5
    assert top["top_journeys"]
    assert top["top_journeys"][0]["route_id"] == (
        result.updated.evaluation.recommended_route.route_id
    )
    assert top["top_journeys"][0]["is_recommended"] is True


def test_replan_unknown_statuses_preserved_in_top5():
    prefs = UserPreferences(time_weight=8.0)
    routes = [
        _route(
            route_id="known",
            travel_time_minutes=40,
            cost=50,
            cost_status="known",
            duration_status="known",
        ),
        _route(
            route_id="unk",
            mode="bus",
            travel_time_minutes=55,
            cost=0,
            cost_status="unknown",
            duration_status="unknown",
            component_modes=["walk", "bus", "walk"],
            walking_distance_meters=None,
            walking_minutes=8,
        ),
    ]
    initial = PlannerResult(
        request=CommuteRequest(user_id="u", origin="A", destination="B", preferences=prefs),
        routes=routes,
        evaluation=evaluate_routes(routes, prefs),
        data_sources=["test"],
        historical_signal_used=False,
    )
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(context_source="none"),
    )
    top = result.updated.evaluation.top_selection
    by_id = {o["route_id"]: o for o in top["top_journeys"]}
    if "unk" in by_id:
        assert by_id["unk"]["cost_status"] == "unknown"
        assert by_id["unk"]["duration_status"] == "unknown"


def test_replan_no_valid_route_empty_top5():
    prefs = UserPreferences(excluded_modes=["cab", "auto", "bus", "metro", "walk"])
    routes = [
        _route(route_id="cab_only", component_modes=["cab"]),
    ]
    initial = PlannerResult(
        request=CommuteRequest(user_id="u", origin="A", destination="B", preferences=prefs),
        routes=routes,
        evaluation=evaluate_routes(routes, prefs),
        data_sources=["test"],
        historical_signal_used=False,
    )
    # Initial may already be no-valid; replan should keep empty top.
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(context_source="none"),
    )
    eval_result = result.updated.evaluation
    assert eval_result is not None
    top = eval_result.top_selection or {}
    if eval_result.recommended_route is None:
        assert (top.get("selected_count") or 0) == 0
        assert (top.get("top_journeys") or []) == []
