"""
Adaptive replanning around the existing plan_commute / evaluate_routes path.

Does not reimplement Maps fetching or scoring. Simulated context overlays are
explicitly labeled and never presented as live Google Maps data.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import List, Optional, Any

from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.planner.models import (
    CommuteRequest,
    ContextChange,
    InvalidReplanInput,
    PlannerResult,
    ReplanResult,
)
from src.planner.service import plan_commute


def _recommended_id(result: Optional[PlannerResult]) -> Optional[str]:
    if result is None or result.evaluation is None:
        return None
    rec = result.evaluation.recommended_route
    return rec.route_id if rec is not None else None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _copy_routes(routes: List[RouteCandidate]) -> List[RouteCandidate]:
    return [deepcopy(r) for r in routes]


def _apply_simulated_overlays(
    routes: List[RouteCandidate],
    change: ContextChange,
    provenance: List[str],
    warnings: List[str],
) -> List[RouteCandidate]:
    """Apply explicit simulated deltas onto RouteCandidate copies."""
    if change.context_source != "simulated":
        return routes

    target = change.target_route_id
    if not target:
        if change.traffic_changed or change.disruption_changed:
            warnings.append("SIMULATED_CONTEXT_MISSING_TARGET_ROUTE")
        return routes

    updated: List[RouteCandidate] = []
    found = False
    for route in routes:
        if route.route_id != target:
            updated.append(route)
            continue
        found = True
        new_cong = route.congestion_score
        new_time = route.travel_time_minutes
        new_disr = route.disruption_risk
        notes = []
        if change.traffic_changed and change.congestion_delta:
            new_cong = _clamp01(route.congestion_score + change.congestion_delta)
            notes.append(
                f"simulated congestion {route.congestion_score:.2f}->{new_cong:.2f}"
            )
        if change.traffic_changed and change.travel_time_delta_minutes:
            new_time = max(0.0, route.travel_time_minutes + change.travel_time_delta_minutes)
            notes.append(
                f"simulated travel_time_minutes {route.travel_time_minutes}->{new_time}"
            )
        if change.disruption_changed and change.disruption_delta:
            new_disr = _clamp01(route.disruption_risk + change.disruption_delta)
            notes.append(
                f"simulated disruption_risk {route.disruption_risk:.2f}->{new_disr:.2f}"
            )
        updated.append(
            replace(
                route,
                congestion_score=new_cong,
                travel_time_minutes=new_time,
                disruption_risk=new_disr,
            )
        )
        for note in notes:
            provenance.append(f"SIMULATED:{route.route_id}:{note}")
        warnings.append(f"SIMULATED_CONTEXT_APPLIED ({route.route_id})")

    if not found:
        warnings.append(f"SIMULATED_TARGET_ROUTE_NOT_FOUND ({target})")
    return updated


def replan_commute(
    initial_request: CommuteRequest,
    initial_result: PlannerResult,
    context_change: ContextChange,
    *,
    api_key: Optional[str] = None,
    models_dir: str = "models",
    cache_ttl: Optional[int] = None,
    refresh_live_routes: bool = False,
) -> ReplanResult:
    """
    Re-evaluate an existing plan under a context change.

    Authority: deterministic evaluate_routes only.
    Live refresh: optional plan_commute() when context_source == "live"
    and refresh_live_routes / updated_departure_time is set.
    Simulated overlays: labeled SIMULATED; never claimed as Maps live data.
    """
    if initial_request is None:
        raise InvalidReplanInput("initial_request is required.")
    if initial_result is None:
        raise InvalidReplanInput("initial_result is required.")
    if context_change is None:
        raise InvalidReplanInput("context_change is required.")
    if context_change.context_source not in {"none", "live", "simulated"}:
        raise InvalidReplanInput(
            f"Invalid context_source: {context_change.context_source}"
        )

    provenance: List[str] = []
    previous_id = _recommended_id(initial_result)

    # --- Live refresh path (real Maps via existing planner) ---
    if (
        context_change.context_source == "live"
        and (refresh_live_routes or context_change.updated_departure_time)
    ):
        new_request = replace(
            initial_request,
            departure_time=(
                context_change.updated_departure_time
                or initial_request.departure_time
            ),
        )
        provenance.append("LIVE:refreshed_candidates_via_plan_commute")
        updated = plan_commute(
            new_request,
            api_key=api_key,
            models_dir=models_dir,
            cache_ttl=cache_ttl,
        )
        updated.warnings = list(updated.warnings) + [
            "CONTEXT_SOURCE_LIVE",
            context_change.description or "live context refresh",
        ]
        new_id = _recommended_id(updated)
        return ReplanResult(
            initial=initial_result,
            updated=updated,
            context_change=context_change,
            recommendation_changed=previous_id != new_id,
            previous_route_id=previous_id,
            new_route_id=new_id,
            provenance_notes=provenance,
        )

    # --- Re-evaluate existing candidates (+ optional simulated overlays) ---
    if initial_result.error and not initial_result.routes:
        raise InvalidReplanInput(
            f"Cannot replan from failed initial result: {initial_result.error}"
        )

    routes = _copy_routes(list(initial_result.routes or []))
    warnings = list(initial_result.warnings or [])
    data_sources = list(initial_result.data_sources or [])

    if context_change.context_source == "none" and not any(
        [
            context_change.traffic_changed,
            context_change.disruption_changed,
            context_change.weather_changed,
            context_change.updated_departure_time,
        ]
    ):
        provenance.append("UNCHANGED_CONTEXT:re_evaluate_only")
        warnings.append("CONTEXT_UNCHANGED")
    elif context_change.context_source == "simulated":
        provenance.append("SIMULATED:demo_context_overlay")
        routes = _apply_simulated_overlays(routes, context_change, provenance, warnings)
        if context_change.weather_changed:
            warnings.append("WEATHER_CHANGED_SIMULATED (not used by scoring)")
            if context_change.weather_note:
                provenance.append(f"SIMULATED:weather_note:{context_change.weather_note}")
        if "simulated_context" not in data_sources:
            data_sources.append("simulated_context")
    elif context_change.context_source == "live":
        # Live flag without refresh: keep candidates, note limited live context.
        provenance.append("LIVE:context_flag_without_candidate_refresh")
        warnings.append("LIVE_CONTEXT_NO_REFRESH")

    if context_change.updated_departure_time and context_change.context_source != "live":
        warnings.append(
            f"DEPARTURE_TIME_UPDATED_IN_REQUEST ({context_change.updated_departure_time})"
        )

    preferences = (
        initial_request.preferences
        if initial_request.preferences is not None
        else UserPreferences()
    )

    try:
        evaluation = evaluate_routes(routes, preferences)
    except Exception as exc:
        updated = PlannerResult(
            request=initial_request,
            routes=routes,
            evaluation=None,
            data_sources=data_sources,
            historical_signal_used=initial_result.historical_signal_used,
            warnings=warnings + ["EVALUATOR_FAILURE"],
            error="EVALUATOR_FAILURE",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
        return ReplanResult(
            initial=initial_result,
            updated=updated,
            context_change=context_change,
            recommendation_changed=False,
            previous_route_id=previous_id,
            new_route_id=None,
            provenance_notes=provenance,
            error="EVALUATOR_FAILURE",
        )

    new_request = initial_request
    if context_change.updated_departure_time:
        new_request = replace(
            initial_request,
            departure_time=context_change.updated_departure_time,
        )

    updated = PlannerResult(
        request=new_request,
        routes=routes,
        evaluation=evaluation,
        data_sources=data_sources,
        historical_signal_used=initial_result.historical_signal_used,
        warnings=warnings,
    )
    new_id = _recommended_id(updated)
    return ReplanResult(
        initial=initial_result,
        updated=updated,
        context_change=context_change,
        recommendation_changed=previous_id != new_id,
        previous_route_id=previous_id,
        new_route_id=new_id,
        provenance_notes=provenance,
    )
