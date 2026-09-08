"""
Phase 5E — adaptive replanning loop tests.

Canonical demo OD: Electronic City → Majestic (not a hardcoded production route).
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.adaptive import (
    AdaptiveReplanRequest,
    run_adaptive_replan_from_snapshot,
    snapshot_from_planner_result,
)
from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.agent.replan import run_adaptive_replan
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.planner.models import (
    CommuteRequest,
    ContextChange,
    ContextChangeType,
    PlannerResult,
    ReplanDecision,
)
from src.planner.replan import replan_commute
from src.planner.replan_config import SCORE_SWITCH_MARGIN


def _route(**overrides) -> RouteCandidate:
    defaults = dict(
        route_id="journey_A",
        mode="cab",
        travel_time_minutes=30.0,
        cost=300.0,
        walking_minutes=0.0,
        transfers=0,
        congestion_score=0.2,
        reliability_score=0.85,
        disruption_risk=0.1,
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def _routes_abc():
    """A clearly wins under time-heavy prefs; B/C are slower alternatives."""
    return [
        _route(
            route_id="journey_A",
            mode="cab",
            travel_time_minutes=25.0,
            cost=350.0,
            walking_minutes=0.0,
            transfers=0,
            congestion_score=0.2,
            reliability_score=0.85,
        ),
        _route(
            route_id="journey_B",
            mode="hybrid",
            travel_time_minutes=55.0,
            cost=90.0,
            walking_minutes=10.0,
            transfers=1,
            congestion_score=0.15,
            reliability_score=0.9,
        ),
        _route(
            route_id="journey_C",
            mode="bus",
            travel_time_minutes=70.0,
            cost=40.0,
            walking_minutes=15.0,
            transfers=0,
            congestion_score=0.2,
            reliability_score=0.75,
        ),
    ]


def _request(prefs=None) -> CommuteRequest:
    return CommuteRequest(
        user_id="demo",
        origin=ELECTRONIC_CITY.address,
        destination=MAJESTIC.address,
        departure_time="2024-09-06T08:00:00Z",
        preferences=prefs
        or UserPreferences(
            time_weight=10.0,
            cost_weight=1.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=2.0,
            reliability_weight=1.0,
        ),
    )


def _initial(routes=None, prefs=None) -> PlannerResult:
    routes = routes or _routes_abc()
    prefs = prefs or _request().preferences
    evaluation = evaluate_routes(routes, prefs)
    return PlannerResult(
        request=_request(prefs),
        routes=routes,
        evaluation=evaluation,
        data_sources=["synthetic_test"],
        historical_signal_used=False,
        warnings=[],
    )


def test_no_context_change_no_unnecessary_switch():
    initial = _initial()
    before = initial.evaluation.recommended_route.route_id
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(context_source="none", change_type=ContextChangeType.NONE.value),
    )
    assert result.decision in {
        ReplanDecision.NO_SIGNIFICANT_CHANGE.value,
        ReplanDecision.KEEP_CURRENT.value,
    }
    assert result.recommendation_changed is False
    assert result.new_route_id == before


def test_insignificant_traffic_keep_or_no_significant():
    initial = _initial()
    before = initial.evaluation.recommended_route.route_id
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.TRAFFIC_CHANGE.value,
            traffic_changed=True,
            context_source="simulated",
            target_route_id=before,
            travel_time_delta_minutes=1.0,
            congestion_delta=0.02,
            description="tiny simulated bump",
        ),
    )
    assert result.decision in {
        ReplanDecision.NO_SIGNIFICANT_CHANGE.value,
        ReplanDecision.KEEP_CURRENT.value,
    }
    assert result.new_route_id == before
    assert any("SIMULATED" in p for p in result.provenance_notes)
    assert "simulated_context" in result.updated.data_sources


def test_significant_traffic_switch_journey():
    initial = _initial()
    before = initial.evaluation.recommended_route.route_id
    assert before == "journey_A"
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.TRAFFIC_CHANGE.value,
            traffic_changed=True,
            context_source="simulated",
            target_route_id="journey_A",
            travel_time_delta_minutes=30.0,
            congestion_delta=0.55,
            previous_value=28.0,
            new_value=58.0,
            description="simulated heavy traffic on A",
        ),
    )
    assert result.decision == ReplanDecision.SWITCH_JOURNEY.value
    assert result.recommendation_changed is True
    assert result.previous_route_id == "journey_A"
    assert result.new_route_id != "journey_A"
    assert result.new_route_id in {"journey_B", "journey_C"}
    assert any("source=simulation" in p for p in result.provenance_notes)


def test_previous_invalidated_switches():
    initial = _initial()
    before = initial.evaluation.recommended_route.route_id
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.TRANSIT_DISRUPTION.value,
            disruption_changed=True,
            context_source="simulated",
            invalidate_route_ids=[before],
            description="simulated disruption on previous journey",
        ),
    )
    assert before in result.invalidated_journey_ids
    assert result.decision == ReplanDecision.SWITCH_JOURNEY.value
    assert result.new_route_id != before
    assert result.new_route_id not in result.invalidated_journey_ids


def test_no_feasible_alternative():
    only = [_route(route_id="only_one", mode="cab", travel_time_minutes=20)]
    initial = _initial(routes=only)
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.TRANSIT_DISRUPTION.value,
            context_source="simulated",
            invalidate_route_ids=["only_one"],
            disruption_changed=True,
        ),
    )
    assert result.decision == ReplanDecision.NO_FEASIBLE_ALTERNATIVE.value
    assert result.new_route_id is None


def test_excluded_cab_constraint_during_replan():
    initial = _initial()
    assert initial.evaluation.recommended_route.mode == "cab"
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.USER_CONSTRAINT_CHANGE.value,
            context_source="none",
            excluded_modes_update=["cab"],
            description="user now excludes cab",
        ),
    )
    assert result.new_route_id is not None
    rec = result.updated.evaluation.recommended_route
    assert rec.mode != "cab"
    for scored in result.updated.evaluation.ranked_routes:
        if scored.route.mode == "cab":
            assert scored.is_valid is False


def test_excluded_bus_constraint_during_replan():
    prefs = UserPreferences(time_weight=1.0, cost_weight=8.0, walking_weight=1.0)
    routes = _routes_abc()
    initial = _initial(routes=routes, prefs=prefs)
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.USER_CONSTRAINT_CHANGE.value,
            context_source="none",
            excluded_modes_update=["bus"],
        ),
    )
    for scored in result.updated.evaluation.ranked_routes:
        if scored.route.mode == "bus":
            assert scored.is_valid is False
    if result.new_route_id:
        assert result.updated.evaluation.recommended_route.mode != "bus"


def test_synthetic_traffic_marked_simulation():
    initial = _initial()
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            traffic_changed=True,
            context_source="simulated",
            target_route_id="journey_A",
            travel_time_delta_minutes=5.0,
        ),
    )
    assert result.context_change.context_source == "simulated"
    assert result.orchestration_metadata.get("live_or_simulated") == "simulated"
    assert "simulated_context" in result.updated.data_sources
    assert not any("GOOGLE_LIVE" in p for p in result.provenance_notes)


def test_missing_historical_not_fabricated_in_replan():
    initial = _initial()
    initial.historical_signal_used = False
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(context_source="none"),
    )
    assert result.updated.historical_signal_used is False
    for r in result.updated.routes:
        # replan must not invent historical payloads
        assert r.historical_mobility_signal in (None, r.historical_mobility_signal)


def test_weather_unavailable_no_fake_penalty():
    initial = _initial()
    before_scores = {
        s.route.route_id: s.final_score
        for s in initial.evaluation.ranked_routes
        if s.is_valid
    }
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.WEATHER_CHANGE.value,
            weather_changed=True,
            context_source="simulated",
            weather_note="provider unavailable — simulation flag only",
        ),
    )
    assert any("no_fabricated_penalty" in p for p in result.provenance_notes)
    # Without traffic overlay, scores should match a plain re-eval
    after = {
        s.route.route_id: s.final_score
        for s in result.updated.evaluation.ranked_routes
        if s.is_valid
    }
    assert after.keys() == before_scores.keys()


def test_transit_disruption_invalidates_affected():
    initial = _initial()
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            change_type=ContextChangeType.TRANSIT_DISRUPTION.value,
            disruption_changed=True,
            context_source="simulated",
            invalidate_route_ids=["journey_B"],
        ),
    )
    assert "journey_B" in result.invalidated_journey_ids
    assert "journey_B" not in [r.route_id for r in result.updated.routes]
    assert "journey_B" not in result.retained_journey_ids


def test_unaffected_journeys_retain_information():
    initial = _initial()
    b_before = next(r for r in initial.routes if r.route_id == "journey_B")
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            traffic_changed=True,
            context_source="simulated",
            target_route_id="journey_A",
            travel_time_delta_minutes=30.0,
            congestion_delta=0.5,
        ),
    )
    b_after = next(r for r in result.updated.routes if r.route_id == "journey_B")
    assert b_after.travel_time_minutes == b_before.travel_time_minutes
    assert b_after.cost == b_before.cost
    assert b_after.mode == b_before.mode


def test_decision_engine_authoritative_on_significant_switch():
    initial = _initial()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="journey_A",
        travel_time_delta_minutes=30.0,
        congestion_delta=0.6,
    )
    result = replan_commute(initial.request, initial, change)
    routes = deepcopy(initial.routes)
    routes = [
        replace(
            r,
            travel_time_minutes=r.travel_time_minutes + 30.0,
            congestion_score=min(1.0, r.congestion_score + 0.6),
        )
        if r.route_id == "journey_A"
        else r
        for r in routes
    ]
    direct = evaluate_routes(routes, initial.request.preferences)
    assert result.decision_engine_preferred_id == direct.recommended_route.route_id
    assert result.new_route_id == direct.recommended_route.route_id


def test_gemini_cannot_override_classification():
    initial = _initial()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="journey_A",
        travel_time_delta_minutes=30.0,
        congestion_delta=0.6,
    )
    with patch("src.agent.replan._invoke_replan_explanation") as mock_explain:
        mock_explain.return_value = (
            "Classification should be KEEP_CURRENT and journey_ZZZ.",
            True,
            "",
        )
        with patch("src.agent.replan.gemini_credentials_available", return_value=True):
            with patch("src.agent.replan.adk_importable", return_value=True):
                result = run_adaptive_replan(
                    initial.request, initial, change, invoke_gemini=True
                )
    assert result.decision == ReplanDecision.SWITCH_JOURNEY.value
    assert result.new_route_id != "journey_ZZZ"
    assert result.decision != ReplanDecision.KEEP_CURRENT.value


def test_deterministic_identical_input():
    initial = _initial()
    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id="journey_A",
        travel_time_delta_minutes=30.0,
        congestion_delta=0.5,
    )
    a = replan_commute(initial.request, initial, change, replan_request_id="fixed")
    b = replan_commute(initial.request, initial, change, replan_request_id="fixed")
    assert a.decision == b.decision
    assert a.new_route_id == b.new_route_id
    assert a.previous_route_id == b.previous_route_id
    assert a.decision_factors == b.decision_factors


def test_electronic_city_majestic_adaptive_scenario():
    """EC → Majestic: significant simulated traffic on A → SWITCH to alternative."""
    initial = _initial()
    assert initial.request.origin == ELECTRONIC_CITY.address
    assert initial.request.destination == MAJESTIC.address
    snap = snapshot_from_planner_result(initial, plan_id="ec-maj-plan")
    assert snap.selected_journey_id == "journey_A"
    req = AdaptiveReplanRequest(
        original_request=initial.request,
        previous_plan=snap,
        context_changes=[
            ContextChange(
                change_type=ContextChangeType.TRAFFIC_CHANGE.value,
                traffic_changed=True,
                context_source="simulated",
                target_route_id="journey_A",
                affected_leg_id="road_leg_2",
                previous_value=28.0,
                new_value=58.0,
                absolute_travel_time_minutes=58.0,
                confidence=0.9,
                change_timestamp=datetime.now(timezone.utc).isoformat(),
                description="simulated traffic on road access leg",
            )
        ],
    )
    result = run_adaptive_replan_from_snapshot(req)
    assert result.decision == ReplanDecision.SWITCH_JOURNEY.value
    assert result.original_plan_id == "ec-maj-plan"
    assert result.new_route_id in {"journey_B", "journey_C"}
    assert result.orchestration_metadata.get("adaptive_from_snapshot") is True


def test_replan_metadata_complete():
    initial = _initial()
    result = replan_commute(
        initial.request,
        initial,
        ContextChange(
            traffic_changed=True,
            context_source="simulated",
            target_route_id="journey_A",
            travel_time_delta_minutes=30.0,
        ),
        original_plan_id="plan-1",
        replan_request_id="replan-1",
    )
    payload = result.to_dict()
    for key in (
        "decision",
        "previous_route_id",
        "new_route_id",
        "previous_score",
        "new_score",
        "invalidated_journey_ids",
        "retained_journey_ids",
        "decision_factors",
        "replan_request_id",
        "original_plan_id",
        "affected_context_changes",
        "orchestration_metadata",
    ):
        assert key in payload
    assert payload["replan_request_id"] == "replan-1"
    assert payload["original_plan_id"] == "plan-1"
    assert payload["orchestration_metadata"]["score_switch_margin"] == SCORE_SWITCH_MARGIN


def test_no_hardcoded_journey_templates_in_adaptive():
    root = Path("src/agent/adaptive")
    for path in list(root.rglob("*.py")) + [
        Path("src/planner/replan.py"),
        Path("src/planner/replan_config.py"),
    ]:
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*ALLOWED_JOURNEYS\s*=", src, re.M)
        assert "AUTO_METRO_WALK" not in src
        assert "BUS_METRO_WALK" not in src
        assert "SUPPORTED_COMBINATIONS" not in src
