"""
API service adapters — HTTP → ADK Mobility Orchestrator.

Phase 6F: planning uses plan_commute_with_adk (capabilities → Journey Builder →
enrichment → Decision Engine → optional Gemini explanation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.adaptive import (
    AdaptiveReplanRequest,
    run_adaptive_replan_from_snapshot,
    snapshot_from_orchestration,
)
from src.agent.config import FALLBACK_NOTICE, gemini_credentials_available
from src.agent.demo_od import BENGALURU_LANDMARKS
from src.agent.orchestrator import (
    OrchestrationResult,
    OrchestratorRequest,
    plan_commute_with_adk,
)
from src.journey_builder.steps import attach_steps_to_top_selection
from src.agent.schemas import recommendation_from_planner
from src.api.schemas import ContextChangeIn, MobilityConstraintsIn, PlanRequest, PreferencesIn
from src.agent.mobility_strategy import (
    AccessoryMode,
    MobilityConstraints,
    merge_excluded_modes,
    parse_strategy,
)
from src.decision_engine.models import (
    PROFILE_BALANCED,
    PROFILE_CHEAPEST,
    PROFILE_FASTEST,
    PROFILE_LOW_TRAFFIC,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    UserPreferences,
    preference_profile,
)
from src.mobility.models import TravelMode
from src.mobility.route_adapter import field_provenance
from src.network.file_repository import FileStaticMobilityRepository
from src.network.repository import StaticMobilityDataRepository
from src.planner.models import CommuteRequest, ContextChange, PlannerResult


_DEFAULT_REPO: Optional[StaticMobilityDataRepository] = None
_OBJECTIVE_TO_PROFILE = {
    "fastest": PROFILE_FASTEST,
    "cheapest": PROFILE_CHEAPEST,
    "low_walking": PROFILE_LOW_WALKING,
    "low-walking": PROFILE_LOW_WALKING,
    "reliable": PROFILE_RELIABLE,
    "low_traffic": PROFILE_LOW_TRAFFIC,
    "low-traffic": PROFILE_LOW_TRAFFIC,
    "balanced": PROFILE_BALANCED,
}


def default_mobility_repository() -> Optional[StaticMobilityDataRepository]:
    """Load published mobility snapshots when present (real Bengaluru network)."""
    global _DEFAULT_REPO
    if _DEFAULT_REPO is not None:
        return _DEFAULT_REPO
    root = Path("data/mobility_network")
    if not root.exists():
        return None
    repo = FileStaticMobilityRepository(root)
    if repo.get_active_snapshot("bmtc") is None and repo.get_active_snapshot("bmrcl") is None:
        return None
    _DEFAULT_REPO = repo
    return _DEFAULT_REPO


def set_mobility_repository(repo: Optional[StaticMobilityDataRepository]) -> None:
    """Test hook to inject / clear the default repository."""
    global _DEFAULT_REPO
    _DEFAULT_REPO = repo


def _merge_preferences(
    prefs: Optional[PreferencesIn],
    *,
    objective: Optional[str],
    preference_profile_name: Optional[str],
) -> UserPreferences:
    """Apply named profile for soft weights, then overlay body hard constraints."""
    profile_key = (preference_profile_name or objective or "").strip()
    if profile_key:
        mapped = _OBJECTIVE_TO_PROFILE.get(profile_key.lower(), profile_key)
        base = preference_profile(mapped)
    else:
        base = UserPreferences()

    if prefs is None:
        return base

    use_profile_weights = bool(profile_key)
    body_looks_default = (
        prefs.time_weight == 1.0
        and prefs.cost_weight == 1.0
        and prefs.walking_weight == 1.0
        and prefs.transfer_weight == 1.0
        and prefs.congestion_weight == 1.0
        and prefs.reliability_weight == 1.0
    )
    if use_profile_weights and body_looks_default:
        tw, cw, ww, xw, gw, rw = (
            base.time_weight,
            base.cost_weight,
            base.walking_weight,
            base.transfer_weight,
            base.congestion_weight,
            base.reliability_weight,
        )
    else:
        tw, cw, ww, xw, gw, rw = (
            prefs.time_weight,
            prefs.cost_weight,
            prefs.walking_weight,
            prefs.transfer_weight,
            prefs.congestion_weight,
            prefs.reliability_weight,
        )

    return UserPreferences(
        time_weight=tw,
        cost_weight=cw,
        walking_weight=ww,
        transfer_weight=xw,
        congestion_weight=gw,
        reliability_weight=rw,
        preferred_modes=prefs.preferred_modes,
        excluded_modes=prefs.excluded_modes,
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
        preferences=_merge_preferences(
            body.preferences,
            objective=body.objective,
            preference_profile_name=body.preference_profile,
        ),
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


def _parse_departure(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _resolve_landmark_coords(label: str):
    place = BENGALURU_LANDMARKS.get((label or "").strip().lower())
    if place:
        return place.latitude, place.longitude
    return None, None


def _constraints_from_body(
    body_constraints: Optional[MobilityConstraintsIn],
) -> Optional[MobilityConstraints]:
    if body_constraints is None:
        return None
    accessories = None
    if body_constraints.allowed_accessory_modes is not None:
        accessories = [
            AccessoryMode.parse(m) for m in body_constraints.allowed_accessory_modes
        ]
    return MobilityConstraints(
        excluded_modes=list(body_constraints.excluded_modes)
        if body_constraints.excluded_modes is not None
        else None,
        max_walking_distance_meters=body_constraints.max_walking_distance_meters,
        max_transfers=body_constraints.max_transfers,
        allowed_accessory_modes=accessories,
    )


def orchestrator_request_from_plan(
    body: PlanRequest,
    *,
    invoke_live_traffic: Optional[bool] = None,
) -> OrchestratorRequest:
    prefs = _merge_preferences(
        body.preferences,
        objective=body.objective,
        preference_profile_name=body.preference_profile,
    )
    strategy = parse_strategy(body.strategy)
    constraints = _constraints_from_body(body.constraints)
    # Preserve existing exclusion behavior: union preferences + constraints.excluded_modes.
    # Strategy / walking-m / transfers / accessories are enforced in evaluate_routes (Phase 7B).
    merged_excluded = merge_excluded_modes(prefs.excluded_modes, constraints)
    if merged_excluded != (list(prefs.excluded_modes) if prefs.excluded_modes else None):
        prefs = UserPreferences(
            time_weight=prefs.time_weight,
            cost_weight=prefs.cost_weight,
            walking_weight=prefs.walking_weight,
            transfer_weight=prefs.transfer_weight,
            congestion_weight=prefs.congestion_weight,
            reliability_weight=prefs.reliability_weight,
            preferred_modes=prefs.preferred_modes,
            excluded_modes=merged_excluded,
            max_walking_minutes=prefs.max_walking_minutes,
            max_cost=prefs.max_cost,
            avoid_heavy_traffic=prefs.avoid_heavy_traffic,
        )

    o_lat, o_lon = _resolve_landmark_coords(body.origin)
    d_lat, d_lon = _resolve_landmark_coords(body.destination)
    if body.origin_lat is not None and body.origin_lon is not None:
        o_lat, o_lon = body.origin_lat, body.origin_lon
    if body.destination_lat is not None and body.destination_lon is not None:
        d_lat, d_lon = body.destination_lat, body.destination_lon

    if invoke_live_traffic is not None:
        traffic = invoke_live_traffic
    elif body.invoke_live_traffic is not None:
        traffic = body.invoke_live_traffic
    else:
        traffic = True

    return OrchestratorRequest(
        user_id=body.user_id,
        origin=body.origin,
        destination=body.destination,
        departure_time=_parse_departure(body.departure_time),
        origin_lat=o_lat,
        origin_lon=o_lon,
        destination_lat=d_lat,
        destination_lon=d_lon,
        preferences=prefs,
        origin_zone=body.origin_zone,
        destination_zone=body.destination_zone,
        strategy=strategy,
        constraints=constraints,
        invoke_gemini=bool(body.invoke_gemini),
        invoke_weather=bool(body.invoke_weather),
        invoke_historical=bool(body.invoke_historical),
        invoke_live_traffic=bool(traffic),
        allow_legacy_maps_fallback=bool(body.allow_legacy_maps_fallback),
        raw_text=f"Plan commute from {body.origin} to {body.destination}.",
    )


def _provenance_block_from_orch(result: OrchestrationResult) -> Dict[str, Any]:
    sources = list(result.recommendation.data_sources or [])
    if result.metadata and result.metadata.network_snapshot_versions:
        sources.append("mobility_network_snapshots")
    if result.enrichment_results:
        sources.append("google_maps_routes")
    return {
        "data_sources": sorted(set(sources)),
        "historical_signal_used": bool(result.recommendation.historical_signal_used),
        "network_snapshot_versions": dict(
            result.metadata.network_snapshot_versions or {}
        ),
        "capabilities": [c.to_dict() for c in (result.metadata.capabilities or [])],
        "field_policy": {
            "DRIVE": field_provenance(TravelMode.DRIVE),
            "TRANSIT": field_provenance(TravelMode.TRANSIT),
            "WALK": field_provenance(TravelMode.WALK),
        },
        "notes": [
            "orchestration = ADK MobilityOrchestrator",
            "decision = Decision Engine (authoritative)",
            "gemini = explanation only",
        ],
    }


def _evaluation_summary_from_orch(result: OrchestrationResult) -> Optional[Dict[str, Any]]:
    evaluation = result.evaluation
    if evaluation is None:
        return None
    rec = evaluation.recommended_route
    return {
        "score": evaluation.score,
        "reason_codes": list(evaluation.reason_codes),
        "recommended_route_id": rec.route_id if rec else None,
        "route_categories": [
            {"category": c.category, "route_id": c.route.route_id}
            for c in (evaluation.route_categories or [])
        ],
        "ranked": [
            {
                "route_id": sr.route.route_id,
                "final_score": sr.final_score,
                "is_valid": sr.is_valid,
                "reason_codes": list(sr.reason_codes),
                "cost_status": getattr(sr.route, "cost_status", None),
                "duration_status": getattr(sr.route, "duration_status", None),
                "mode_signature": getattr(sr.route, "mode_signature", None),
            }
            for sr in evaluation.ranked_routes
        ],
    }


def _winning_journey(
    result: OrchestrationResult,
    *,
    origin_label: Optional[str] = None,
    destination_label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Full journey matching Decision Engine winner (legs/statuses intact)."""
    rec_id = None
    if result.decision and result.decision.recommended_route_id:
        rec_id = result.decision.recommended_route_id
    elif result.evaluation and result.evaluation.recommended_route:
        rec_id = result.evaluation.recommended_route.route_id
    if not rec_id:
        return None
    for j in result.journeys:
        if j.candidate_id == rec_id:
            return j.to_dict(
                origin_label=origin_label,
                destination_label=destination_label,
            )
    return None


def _top_journeys_from_evaluation(evaluation) -> Optional[List[Dict[str, Any]]]:
    """Phase 7C diverse Top-5 list (recommended first)."""
    if evaluation is None:
        return None
    top = getattr(evaluation, "top_selection", None)
    if not top:
        return None
    if isinstance(top, dict):
        return list(top.get("top_journeys") or [])
    return None


def serialize_orchestration_response(
    result: OrchestrationResult,
    *,
    origin_label: Optional[str] = None,
    destination_label: Optional[str] = None,
) -> Dict[str, Any]:
    rec = result.recommendation
    winner = _winning_journey(
        result,
        origin_label=origin_label,
        destination_label=destination_label,
    )
    top_selection = (
        dict(result.evaluation.top_selection)
        if result.evaluation and result.evaluation.top_selection
        else None
    )
    top_selection = attach_steps_to_top_selection(
        top_selection,
        result.journeys,
        origin_label=origin_label,
        destination_label=destination_label,
    )
    top_journeys = (
        list(top_selection.get("top_journeys") or []) if top_selection else None
    )
    return {
        "ok": rec.error is None
        and (rec.recommended_route is not None or bool(result.journeys)),
        "orchestration": "adk_mobility_orchestrator",
        "request": {},
        "recommendation": rec.recommended_route.to_dict()
        if rec.recommended_route
        else None,
        "recommended_journey": winner,
        "alternatives": [r.to_dict() for r in rec.alternatives],
        "top_journeys": top_journeys,
        "top_selection": top_selection,
        "journeys": [
            j.to_dict(
                origin_label=origin_label,
                destination_label=destination_label,
            )
            for j in result.journeys
        ],
        "explanation": rec.explanation,
        "reasons": list(rec.reason_codes),
        "evaluation": _evaluation_summary_from_orch(result),
        "decision": result.decision.to_dict() if result.decision else None,
        "data_sources": list(rec.data_sources),
        "provenance": _provenance_block_from_orch(result),
        "historical_context": result.historical.to_dict() if result.historical else None,
        "historical_signal_used": rec.historical_signal_used,
        "weather_context": result.weather.to_dict() if result.weather else None,
        "warnings": list(rec.warnings),
        "error": rec.error,
        "error_detail": None,
        "gemini": {
            "available": result.gemini_available,
            "invoked": result.gemini_invoked,
            "adk_invoked": result.adk_invoked,
            "mode": result.mode,
        },
        "metadata": result.metadata.to_dict() if result.metadata else None,
        "candidate_count": len(result.journeys),
        "routes": [c.to_dict() for c in result.route_candidates],
    }


def _provenance_block(planner_result: PlannerResult) -> Dict[str, Any]:
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
        "route_categories": [
            {"category": c.category, "route_id": c.route.route_id}
            for c in (evaluation.route_categories or [])
        ],
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
    """Legacy Maps-planner serialization (compat / fallback payloads)."""
    recommendation = recommendation_from_planner(planner_result, explanation)
    top_selection = (
        planner_result.evaluation.top_selection
        if planner_result.evaluation
        else None
    )
    return {
        "ok": planner_result.error is None,
        "orchestration": "legacy_maps_planner",
        "request": planner_result.request.to_dict(),
        "recommendation": recommendation.recommended_route.to_dict()
        if recommendation.recommended_route
        else None,
        "recommended_journey": None,
        "alternatives": [r.to_dict() for r in recommendation.alternatives],
        "top_journeys": (
            list(top_selection.get("top_journeys") or [])
            if isinstance(top_selection, dict)
            else None
        ),
        "top_selection": dict(top_selection) if top_selection else None,
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


def execute_plan(
    body: PlanRequest,
    *,
    repository: Optional[StaticMobilityDataRepository] = None,
    traffic_get_routes=None,
) -> Dict[str, Any]:
    """
    Primary planning path: ADK Mobility Orchestrator.

    HTTP → plan_commute_with_adk → capabilities → Decision Engine → response.
    """
    repo = repository if repository is not None else default_mobility_repository()
    orch_req = orchestrator_request_from_plan(body)

    result = plan_commute_with_adk(
        orch_req,
        repository=repo,
        traffic_get_routes=traffic_get_routes,
    )
    payload = serialize_orchestration_response(
        result,
        origin_label=body.origin,
        destination_label=body.destination,
    )
    payload["request"] = {
        "user_id": body.user_id,
        "origin": body.origin,
        "destination": body.destination,
        "departure_time": body.departure_time,
        "objective": body.objective,
        "preference_profile": body.preference_profile,
        "strategy": body.strategy,
        "constraints": body.constraints.model_dump() if body.constraints else None,
        "origin_zone": body.origin_zone,
        "destination_zone": body.destination_zone,
        "preferences": body.preferences.model_dump() if body.preferences else None,
    }
    if result.recommendation.error:
        payload["ok"] = False
        payload["error"] = result.recommendation.error
    return payload


def execute_replan(body) -> Dict[str, Any]:
    """Plan via ADK orchestrator, then adaptive replan on the snapshot."""
    from src.api.schemas import ReplanRequest

    if not isinstance(body, ReplanRequest):
        raise TypeError("ReplanRequest required")

    change = context_change_from_body(body.context_change)
    repo = default_mobility_repository()

    orch_req = orchestrator_request_from_plan(
        body.request,
        invoke_live_traffic=body.refresh_live_routes,
    )
    if not body.refresh_live_routes:
        orch_req.invoke_live_traffic = False

    orch = plan_commute_with_adk(orch_req, repository=repo)
    if orch.recommendation.error and not orch.journeys and not orch.route_candidates:
        return {
            "ok": False,
            "error": orch.recommendation.error,
            "error_detail": None,
            "warnings": list(orch.recommendation.warnings),
            "previous_recommendation": None,
            "new_recommendation": None,
            "recommendation": None,
            "top_journeys": [],
            "top_selection": {
                "recommended": None,
                "alternatives": [],
                "selected_count": 0,
                "max_count": 5,
                "top_journeys": [],
            },
            "context_change": change.to_dict(),
            "explanation": FALLBACK_NOTICE,
            "provenance": _provenance_block_from_orch(orch),
            "gemini": {
                "available": gemini_credentials_available(),
                "invoked": False,
                "adk_invoked": False,
                "mode": "deterministic_fallback",
            },
            "orchestration": "adk_mobility_orchestrator",
        }

    snapshot = snapshot_from_orchestration(orch)
    # Prefer snapshot request (has preferences) over synthetic defaults.
    original = commute_request_from_plan(body.request)
    snapshot.request = original
    snapshot.planner_result = PlannerResult(
        request=original,
        routes=list(snapshot.routes),
        evaluation=snapshot.evaluation,
        data_sources=list(snapshot.data_sources),
        historical_signal_used=bool(orch.recommendation.historical_signal_used),
        warnings=list(orch.recommendation.warnings),
    )

    if (
        change.context_source == "simulated"
        and change.traffic_changed
        and not change.target_route_id
        and snapshot.selected_journey_id
    ):
        change.target_route_id = snapshot.selected_journey_id

    adaptive_req = AdaptiveReplanRequest(
        original_request=original,
        previous_plan=snapshot,
        context_changes=[change],
        invoke_gemini=bool(body.invoke_gemini),
    )
    replan = run_adaptive_replan_from_snapshot(adaptive_req)

    # Optional Gemini explanation on replan (never changes ranking).
    if body.invoke_gemini and not replan.gemini_invoked:
        # Adaptive path is deterministic; surface fallback notice when Gemini off.
        if not replan.explanation:
            replan.explanation = FALLBACK_NOTICE
        replan.gemini_available = gemini_credentials_available()
        replan.mode = replan.mode or "deterministic_fallback"

    prev_route = next(
        (r for r in snapshot.routes if r.route_id == snapshot.selected_journey_id),
        snapshot.routes[0] if snapshot.routes else None,
    )
    evaluation = replan.updated.evaluation if replan.updated else None
    new_rec = evaluation.recommended_route if evaluation else None
    top_selection = (
        dict(evaluation.top_selection)
        if evaluation and evaluation.top_selection
        else None
    )
    origin_label = getattr(body.request, "origin", None)
    destination_label = getattr(body.request, "destination", None)
    top_selection = attach_steps_to_top_selection(
        top_selection,
        orch.journeys,
        origin_label=origin_label,
        destination_label=destination_label,
    )
    if top_selection is None:
        top_selection = {
            "recommended": None,
            "alternatives": [],
            "selected_count": 0,
            "max_count": 5,
            "top_journeys": [],
        }
    top_journeys = list(top_selection.get("top_journeys") or [])

    return {
        "ok": replan.updated.error is None and replan.error is None,
        "orchestration": "adk_adaptive_replan",
        "recommendation_changed": replan.recommendation_changed,
        "previous_route_id": replan.previous_route_id,
        "new_route_id": replan.new_route_id,
        "decision": replan.decision,
        # Plan-aligned aliases (Phase 7E) — same DE Top-5 pipeline as /plan.
        "recommendation": new_rec.to_dict() if new_rec else None,
        "top_journeys": top_journeys,
        "top_selection": top_selection,
        "previous_recommendation": prev_route.to_dict() if prev_route else None,
        "new_recommendation": new_rec.to_dict() if new_rec else None,
        "context_change": replan.context_change.to_dict(),
        "explanation": replan.explanation or FALLBACK_NOTICE,
        "before": {
            "recommended_route_id": snapshot.selected_journey_id,
            "scores": dict(snapshot.scores),
        },
        "after": _evaluation_summary(replan.updated),
        "reasons": {
            "before": [],
            "after": list(evaluation.reason_codes) if evaluation else [],
        },
        "data_sources": list(replan.updated.data_sources),
        "provenance": {
            **_provenance_block(replan.updated),
            "replan_notes": list(replan.provenance_notes),
            "context_source": change.context_source,
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
        "initial_request": original.to_dict(),
        "updated_request": replan.updated.request.to_dict(),
        "plan_id": snapshot.plan_id,
        "replan_decision_factors": list(replan.decision_factors),
    }
