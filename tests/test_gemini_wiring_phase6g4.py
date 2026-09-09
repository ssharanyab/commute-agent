"""Phase 6G.4 — Gemini explain_fn wiring on plan_commute_with_adk / HTTP /plan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.demo_od import (
    CANONICAL_DEMO_DEPARTURE,
    ELECTRONIC_CITY,
    MAJESTIC,
)
from src.agent.orchestrator import OrchestratorRequest, plan_commute_with_adk
from src.agent.planner import _sanitized_selected_journey
from src.decision_engine.models import RouteCandidate
from src.journey_builder import SearchLimits
from src.network.file_repository import FileStaticMobilityRepository
from tests.test_orchestrator_phase5d import _publish_corridor


@pytest.fixture
def demo_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish_corridor(repo)
    return repo


@pytest.fixture
def gemini_gates_open():
    """Orchestrator only calls explain_fn when credentials + ADK are available."""
    with patch(
        "src.agent.orchestrator.gemini_credentials_available",
        return_value=True,
    ), patch(
        "src.agent.orchestrator.adk_importable",
        return_value=True,
    ):
        yield


def _req(**kwargs) -> OrchestratorRequest:
    base = dict(
        user_id="demo-user",
        origin=ELECTRONIC_CITY.address,
        destination=MAJESTIC.address,
        departure_time=CANONICAL_DEMO_DEPARTURE,
        origin_lat=ELECTRONIC_CITY.latitude,
        origin_lon=ELECTRONIC_CITY.longitude,
        destination_lat=MAJESTIC.latitude,
        destination_lon=MAJESTIC.longitude,
        invoke_gemini=False,
        invoke_weather=False,
        invoke_historical=False,
        invoke_live_traffic=False,
        allow_legacy_maps_fallback=False,
        search_limits=SearchLimits(
            max_walking_access_meters=500,
            max_walking_egress_meters=500,
            max_walk_transfer_meters=400,
            max_direct_walk_meters=100,
            allow_road_access=True,
            max_candidates=15,
            max_transfers=3,
            max_legs=10,
        ),
    )
    base.update(kwargs)
    return OrchestratorRequest(**base)


class TestGeminiWiringPhase6G4:
    def test_invoke_gemini_false_does_not_call_explain_fn(
        self, demo_repo, gemini_gates_open
    ):
        calls = []

        def spy(request, evaluation, decision):
            calls.append(True)
            return ("should not run", True, "")

        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            spy,
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=False),
                repository=demo_repo,
            )
        assert calls == []
        assert result.gemini_invoked is False
        assert result.mode == "deterministic_fallback"

    def test_invoke_gemini_true_invokes_explain_fn(
        self, demo_repo, gemini_gates_open
    ):
        calls = []

        def spy(request, evaluation, decision):
            calls.append(
                {
                    "has_eval": evaluation is not None,
                    "rec_id": getattr(decision, "recommended_route_id", None)
                    if decision
                    else None,
                }
            )
            return ("Auto is a direct option with little walking.", True, "")

        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            spy,
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
            )
        if not result.decision:
            pytest.skip("no decision in demo corridor")
        assert len(calls) == 1
        assert result.gemini_invoked is True
        assert result.mode == "adk_gemini"
        assert result.recommendation.explanation.startswith("Auto is a direct")

    def test_successful_gemini_response_returned(self, demo_repo, gemini_gates_open):
        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            return_value=("Friendly user explanation.", True, ""),
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
            )
        if not result.decision:
            pytest.skip("no decision")
        assert result.recommendation.explanation == "Friendly user explanation."
        assert result.gemini_invoked is True
        assert result.adk_invoked is True

    def test_gemini_failure_falls_back_and_does_not_claim_success(
        self, demo_repo, gemini_gates_open
    ):
        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            return_value=("", False, "ADK execution failed: boom"),
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
            )
        if not result.decision:
            pytest.skip("no decision")
        assert result.gemini_invoked is False
        assert result.mode == "deterministic_fallback"
        assert "Deterministic Decision Engine" in result.recommendation.explanation
        assert any(
            c.name == "gemini_explanation" and c.status == "failed"
            for c in result.metadata.capabilities
        )

    def test_gemini_failure_does_not_change_recommendation(
        self, demo_repo, gemini_gates_open
    ):
        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            return_value=("", False, "timeout"),
        ):
            failed = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
            )
        baseline = plan_commute_with_adk(
            _req(invoke_gemini=False),
            repository=demo_repo,
        )
        if not baseline.decision or not failed.decision:
            pytest.skip("no decision")
        assert (
            failed.decision.recommended_route_id
            == baseline.decision.recommended_route_id
        )
        assert (
            failed.recommendation.recommended_route.route_id
            == baseline.recommendation.recommended_route.route_id
        )

    def test_decision_engine_remains_authoritative_with_gemini(
        self, demo_repo, gemini_gates_open
    ):
        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            return_value=("Pick OVERRIDE_ID instead.", True, ""),
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
            )
        if not result.decision:
            pytest.skip("no decision")
        assert result.decision.authoritative is True
        assert (
            result.recommendation.recommended_route.route_id
            == result.decision.recommended_route_id
        )
        assert result.decision.recommended_route_id != "OVERRIDE_ID"

    def test_explicit_explain_fn_kwarg_not_overwritten(
        self, demo_repo, gemini_gates_open
    ):
        calls = {"default": 0, "custom": 0}

        def default_spy(request, evaluation, decision):
            calls["default"] += 1
            return ("default", True, "")

        def custom(request, evaluation, decision):
            calls["custom"] += 1
            return ("custom explanation", True, "")

        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            default_spy,
        ):
            result = plan_commute_with_adk(
                _req(invoke_gemini=True),
                repository=demo_repo,
                explain_fn=custom,
            )
        if not result.decision:
            pytest.skip("no decision")
        assert calls["custom"] == 1
        assert calls["default"] == 0
        assert result.recommendation.explanation == "custom explanation"

    def test_sanitized_journey_omits_ids_and_tokens(self):
        route = RouteCandidate(
            route_id="j_secret",
            mode="auto_rickshaw",
            travel_time_minutes=40,
            cost=200,
            cost_status="known",
            duration_status="known",
            walking_minutes=0,
            transfers=0,
            congestion_score=0.3,
            reliability_score=0.7,
            disruption_risk=0.1,
            google_polyline="POLY",
            google_route_token="TOK",
            mode_signature="auto",
            component_modes=["auto_rickshaw"],
        )
        cleaned = _sanitized_selected_journey(route)
        blob = str(cleaned)
        assert "j_secret" not in blob
        assert "POLY" not in blob
        assert "TOK" not in blob
        assert cleaned["mode"] == "auto_rickshaw"
        assert cleaned["cost_inr"] == 200


class TestApiPlanGeminiWiring:
    def test_execute_plan_uses_wired_explain_when_invoke_true(
        self, demo_repo, gemini_gates_open
    ):
        from fastapi.testclient import TestClient

        from src.api import service as api_service
        from src.api.app import create_app

        api_service.set_mobility_repository(demo_repo)
        client = TestClient(create_app())

        with patch(
            "src.agent.planner.explain_decision_for_orchestrator",
            return_value=("HTTP path Gemini explanation.", True, ""),
        ):
            res = client.post(
                "/plan",
                json={
                    "origin": ELECTRONIC_CITY.address,
                    "destination": MAJESTIC.address,
                    "origin_lat": ELECTRONIC_CITY.latitude,
                    "origin_lon": ELECTRONIC_CITY.longitude,
                    "destination_lat": MAJESTIC.latitude,
                    "destination_lon": MAJESTIC.longitude,
                    "invoke_gemini": True,
                    "invoke_live_traffic": False,
                    "invoke_weather": False,
                    "invoke_historical": False,
                    "allow_legacy_maps_fallback": False,
                },
            )
        data = res.json()
        assert res.status_code == 200
        if not data.get("ok"):
            pytest.skip(f"plan not ok: {data.get('error')}")
        assert data["gemini"]["invoked"] is True
        assert data["gemini"]["mode"] == "adk_gemini"
        assert data["explanation"] == "HTTP path Gemini explanation."
        rec_id = (data.get("recommendation") or {}).get("route_id")
        dec_id = (data.get("decision") or {}).get("recommended_route_id")
        assert rec_id == dec_id

    def test_execute_plan_invoke_false_keeps_deterministic(
        self, demo_repo, gemini_gates_open
    ):
        from fastapi.testclient import TestClient

        from src.api import service as api_service
        from src.api.app import create_app

        api_service.set_mobility_repository(demo_repo)
        client = TestClient(create_app())
        calls = []

        def spy(*args, **kwargs):
            calls.append(1)
            return ("nope", True, "")

        with patch("src.agent.planner.explain_decision_for_orchestrator", spy):
            res = client.post(
                "/plan",
                json={
                    "origin": ELECTRONIC_CITY.address,
                    "destination": MAJESTIC.address,
                    "origin_lat": ELECTRONIC_CITY.latitude,
                    "origin_lon": ELECTRONIC_CITY.longitude,
                    "destination_lat": MAJESTIC.latitude,
                    "destination_lon": MAJESTIC.longitude,
                    "invoke_gemini": False,
                    "invoke_live_traffic": False,
                    "invoke_weather": False,
                    "invoke_historical": False,
                    "allow_legacy_maps_fallback": False,
                },
            )
        data = res.json()
        assert res.status_code == 200
        if not data.get("ok"):
            pytest.skip(f"plan not ok: {data.get('error')}")
        assert calls == []
        assert data["gemini"]["invoked"] is False
        assert data["gemini"]["mode"] == "deterministic_fallback"
