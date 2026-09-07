"""
API service adapters — call existing planner/replan/agent code only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agent.config import (
    FALLBACK_NOTICE,
    adk_importable,
    gemini_credentials_available,
)
from src.agent.planner import (
    MODE_ADK_GEMINI,
    MODE_DETERMINISTIC_FALLBACK,
    _invoke_adk_explanation,
)
from src.agent.replan import run_adaptive_replan
from src.agent.schemas import recommendation_from_planner
from src.api.schemas import ContextChangeIn, PlanRequest, PreferencesIn
from src.decision_engine.models import UserPreferences
from src.mobility.models import TravelMode
from src.mobility.route_adapter import field_provenance
from src.planner.models import CommuteRequest, ContextChange, PlannerResult
from src.planner.service import plan_commute


def _preferences_from_body(prefs: Optional[PreferencesIn]) -> UserPreferences:
    if prefs is None:
        return UserPreferences()
    return UserPreferences(
        time_weight=prefs.time_weight,
        cost_weight=prefs.cost_weight,
        walking_weight=prefs.walking_weight,
        transfer_weight=prefs.transfer_weight,
        congestion_weight=prefs.congestion_weight,
        reliability_weight=prefs.reliability_weight,
        preferred_modes=prefs.preferred_modes,
        max_walking_minutes=prefs.max_walking_minutes,
        max_cost=prefs.max_cost,
        avoid_heavy_traffic=prefs.avoid_heavy_traffic,
    )


def commute_request_from_plan(body: PlanRequest) -> CommuteRequest:
    return CommuteRequest(
        user_id=body.user_id,
        origin=body.origin,
        destination=body.destination,
        departure_time=body.departure_time,
        objective=body.objective,
        preferences=_preferences_from_body(body.preferences),
        origin_zone=body.origin_zone,
        destination_zone=body.destination_zone,
        modes=body.modes,
    )


def context_change_from_body(body: ContextChangeIn) -> ContextChange:
    return ContextChange(
        traffic_changed=body.traffic_changed,
        disruption_changed=body.disruption_changed,
        weather_changed=body.weather_changed,
        updated_departure_time=body.updated_departure_time,
        context_source=body.context_source,
        target_route_id=body.target_route_id,
        congestion_delta=body.congestion_delta,
        travel_time_delta_minutes=body.travel_time_delta_minutes,
        disruption_delta=body.disruption_delta,
        weather_note=body.weather_note,
        description=body.description,
    )


def _provenance_block(planner_result: PlannerResult) -> Dict[str, Any]:
    """Static adapter provenance + result data sources (no fabricated Maps facts)."""
    return {
        "data_sources": list(planner_result.data_sources),
        "historical_signal_used": bool(planner_result.historical_signal_used),
        "field_policy": {
            "DRIVE": field_provenance(TravelMode.DRIVE),
            "TRANSIT": field_provenance(TravelMode.TRANSIT),
            "WALK": field_provenance(TravelMode.WALK),
        },
        "notes": [
            "live = Maps API field via adapter",
            "heuristic = adapter estimate (not a Maps price/reliability feed)",
            "simulated = explicit demo context overlay when present in data_sources",
        ],
    }


def _evaluation_summary(planner_result: PlannerResult) -> Optional[Dict[str, Any]]:
    evaluation = planner_result.evaluation
    if evaluation is None:
        return None
    rec = evaluation.recommended_route
    return {
        "score": evaluation.score,
        "reason_codes": list(evaluation.reason_codes),
        "recommended_route_id": rec.route_id if rec else None,
        "ranked": [
            {
                "route_id": sr.route.route_id,
                "final_score": sr.final_score,
                "is_valid": sr.is_valid,
                "reason_codes": list(sr.reason_codes),
            }
            for sr in evaluation.ranked_routes
        ],
    }


def serialize_plan_response(
    planner_result: PlannerResult,
    *,
    explanation: str,
    gemini_available: bool,
    gemini_invoked: bool,
    adk_invoked: bool,
    mode: str,
) -> Dict[str, Any]:
    recommendation = recommendation_from_planner(planner_result, explanation)
    return {
        "ok": planner_result.error is None,
        "request": planner_result.request.to_dict(),
        "recommendation": recommendation.recommended_route.to_dict()
        if recommendation.recommended_route
        else None,
        "alternatives": [r.to_dict() for r in recommendation.alternatives],
        "explanation": recommendation.explanation,
        "reasons": list(recommendation.reason_codes),
        "evaluation": _evaluation_summary(planner_result),
        "data_sources": list(recommendation.data_sources),
        "provenance": _provenance_block(planner_result),
        "historical_signal_used": recommendation.historical_signal_used,
        "warnings": list(recommendation.warnings),
        "error": recommendation.error,
        "error_detail": planner_result.error_detail,
        "gemini": {
            "available": gemini_available,
            "invoked": gemini_invoked,
            "adk_invoked": adk_invoked,
            "mode": mode,
        },
        "routes": [r.to_dict() for r in planner_result.routes],
    }


def execute_plan(body: PlanRequest) -> Dict[str, Any]:
    """Run existing plan_commute + optional Gemini explanation."""
    commute = commute_request_from_plan(body)
    planner_result = plan_commute(commute)

    gemini_available = gemini_credentials_available()
    gemini_invoked = False
    adk_invoked = False
    mode = MODE_DETERMINISTIC_FALLBACK
    explanation = FALLBACK_NOTICE
    warnings = list(planner_result.warnings)

    if (
        body.invoke_gemini
        and gemini_available
        and adk_importable()
        and planner_result.error is None
    ):
        text, success, err = _invoke_adk_explanation(
            f"Plan commute from {body.origin} to {body.destination}.",
            planner_result,
            user_id=body.user_id,
        )
        if success and text:
            explanation = text
            gemini_invoked = True
            adk_invoked = True
            mode = MODE_ADK_GEMINI
        else:
            if err:
                warnings.append(err)
            planner_result.warnings = warnings

    payload = serialize_plan_response(
        planner_result,
        explanation=explanation,
        gemini_available=gemini_available,
        gemini_invoked=gemini_invoked,
        adk_invoked=adk_invoked,
        mode=mode,
    )
    # Keep warnings from explanation path
    if warnings and payload.get("warnings") is not None:
        merged = list(dict.fromkeys(list(payload["warnings"]) + warnings))
        payload["warnings"] = merged
    return payload


def execute_replan(body) -> Dict[str, Any]:
    """Plan (if needed) then run_adaptive_replan."""
    from src.api.schemas import ReplanRequest

    if not isinstance(body, ReplanRequest):
        raise TypeError("ReplanRequest required")

    commute = commute_request_from_plan(body.request)
    initial = plan_commute(commute)
    change = context_change_from_body(body.context_change)

    # If initial Maps planning failed, do not fabricate a replan.
    if initial.error and not initial.routes:
        return {
            "ok": False,
            "error": initial.error,
            "error_detail": initial.error_detail,
            "warnings": list(initial.warnings),
            "previous_recommendation": None,
            "new_recommendation": None,
            "context_change": change.to_dict(),
            "explanation": FALLBACK_NOTICE,
            "provenance": _provenance_block(initial),
            "gemini": {
                "available": gemini_credentials_available(),
                "invoked": False,
                "adk_invoked": False,
                "mode": MODE_DETERMINISTIC_FALLBACK,
            },
        }

    # Default simulated target to current recommendation when omitted.
    if (
        change.context_source == "simulated"
        and change.traffic_changed
        and not change.target_route_id
        and initial.evaluation
        and initial.evaluation.recommended_route
    ):
        change.target_route_id = initial.evaluation.recommended_route.route_id

    replan = run_adaptive_replan(
        commute,
        initial,
        change,
        user_id=body.request.user_id,
        invoke_gemini=body.invoke_gemini,
        refresh_live_routes=body.refresh_live_routes,
    )

    prev = recommendation_from_planner(replan.initial, explanation="")
    new = recommendation_from_planner(replan.updated, explanation=replan.explanation)

    return {
        "ok": replan.updated.error is None,
        "recommendation_changed": replan.recommendation_changed,
        "previous_route_id": replan.previous_route_id,
        "new_route_id": replan.new_route_id,
        "previous_recommendation": prev.recommended_route.to_dict()
        if prev.recommended_route
        else None,
        "new_recommendation": new.recommended_route.to_dict()
        if new.recommended_route
        else None,
        "context_change": replan.context_change.to_dict(),
        "explanation": replan.explanation,
        "before": _evaluation_summary(replan.initial),
        "after": _evaluation_summary(replan.updated),
        "reasons": {
            "before": list(prev.reason_codes),
            "after": list(new.reason_codes),
        },
        "data_sources": list(replan.updated.data_sources),
        "provenance": {
            **_provenance_block(replan.updated),
            "replan_notes": list(replan.provenance_notes),
        },
        "warnings": list(replan.updated.warnings),
        "error": replan.updated.error or replan.error,
        "error_detail": replan.updated.error_detail,
        "gemini": {
            "available": replan.gemini_available,
            "invoked": replan.gemini_invoked,
            "adk_invoked": replan.adk_invoked,
            "mode": replan.mode,
        },
        "initial_request": replan.initial.request.to_dict(),
        "updated_request": replan.updated.request.to_dict(),
    }
