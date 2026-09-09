"""
Adaptive replanning around the existing plan_commute / evaluate_routes path.

Does not reimplement Maps fetching or scoring. Simulated context overlays are
explicitly labeled and never presented as live Google Maps data.

Phase 5E adds KEEP/SWITCH/NO_FEASIBLE/NO_SIGNIFICANT_CHANGE classification
using named thresholds — Gemini never chooses the classification.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from src.decision_engine.models import EvaluationResult, RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.top5 import select_top_journeys
from src.planner.models import (
    CommuteRequest,
    ContextChange,
    ContextChangeType,
    InvalidReplanInput,
    PlannerResult,
    ReplanDecision,
    ReplanResult,
)
from src.planner.replan_config import (
    SCORE_SWITCH_MARGIN,
    TRAVEL_TIME_INSIGNIFICANT_MINUTES,
    TRAVEL_TIME_SIGNIFICANT_MINUTES,
)
from src.planner.service import plan_commute


def _recommended_id(result: Optional[PlannerResult]) -> Optional[str]:
    if result is None or result.evaluation is None:
        return None
    rec = result.evaluation.recommended_route
    return rec.route_id if rec is not None else None


def _score_map(evaluation: Optional[EvaluationResult]) -> Dict[str, float]:
    if evaluation is None:
        return {}
    return {
        s.route.route_id: float(s.final_score)
        for s in evaluation.ranked_routes
        if s.is_valid
    }


def _valid_ids(evaluation: Optional[EvaluationResult]) -> List[str]:
    if evaluation is None:
        return []
    return [s.route.route_id for s in evaluation.ranked_routes if s.is_valid]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _copy_routes(routes: List[RouteCandidate]) -> List[RouteCandidate]:
    return [deepcopy(r) for r in routes]


def _merge_preferences(
    base: Optional[UserPreferences], change: ContextChange
) -> UserPreferences:
    prefs = base if base is not None else UserPreferences()
    excluded = list(prefs.excluded_modes) if prefs.excluded_modes else []
    if change.excluded_modes_update is not None:
        for mode in change.excluded_modes_update:
            if mode not in excluded:
                excluded.append(mode)
    max_walk = prefs.max_walking_minutes
    if change.max_walking_minutes_update is not None:
        max_walk = change.max_walking_minutes_update
    return replace(
        prefs,
        excluded_modes=excluded or prefs.excluded_modes,
        max_walking_minutes=max_walk,
    )


def _has_meaningful_context(change: ContextChange) -> bool:
    if change.inferred_change_type() != ContextChangeType.NONE.value:
        if change.inferred_change_type() != ContextChangeType.NONE.value and (
            change.traffic_changed
            or change.disruption_changed
            or change.weather_changed
            or change.invalidate_route_ids
            or change.excluded_modes_update is not None
            or change.absolute_travel_time_minutes is not None
            or abs(change.travel_time_delta_minutes) > 0
            or abs(change.congestion_delta) > 0
            or change.updated_departure_time
        ):
            return True
    return any(
        [
            change.traffic_changed,
            change.disruption_changed,
            change.weather_changed,
            change.updated_departure_time,
            change.invalidate_route_ids,
            change.excluded_modes_update is not None,
        ]
    )


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
    needs_overlay = (
        change.traffic_changed
        or change.disruption_changed
        or change.absolute_travel_time_minutes is not None
        or abs(change.travel_time_delta_minutes) > 0
        or abs(change.congestion_delta) > 0
    )
    if not needs_overlay:
        return routes

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
        if change.absolute_travel_time_minutes is not None:
            new_time = max(0.0, float(change.absolute_travel_time_minutes))
            notes.append(
                f"simulated absolute travel_time_minutes "
                f"{route.travel_time_minutes}->{new_time}"
            )
        elif change.traffic_changed and change.travel_time_delta_minutes:
            new_time = max(
                0.0, route.travel_time_minutes + change.travel_time_delta_minutes
            )
            notes.append(
                f"simulated travel_time_minutes {route.travel_time_minutes}->{new_time}"
            )
        if change.traffic_changed and change.congestion_delta:
            new_cong = _clamp01(route.congestion_score + change.congestion_delta)
            notes.append(
                f"simulated congestion {route.congestion_score:.2f}->{new_cong:.2f}"
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
        provenance.append("SIMULATED:source=simulation")

    if not found:
        warnings.append(f"SIMULATED_TARGET_ROUTE_NOT_FOUND ({target})")
    return updated


def _invalidate_routes(
    routes: List[RouteCandidate],
    invalidate_ids: Optional[List[str]],
    provenance: List[str],
    warnings: List[str],
) -> Tuple[List[RouteCandidate], List[str]]:
    """Remove disrupted journeys from the candidate set (hard invalidation)."""
    if not invalidate_ids:
        return routes, []
    drop = set(invalidate_ids)
    kept = [r for r in routes if r.route_id not in drop]
    removed = [rid for rid in invalidate_ids if any(r.route_id == rid for r in routes)]
    for rid in removed:
        provenance.append(f"INVALIDATED:{rid}:TRANSIT_DISRUPTION_OR_EXPLICIT")
        warnings.append(f"JOURNEY_INVALIDATED ({rid})")
    return kept, removed


def classify_replan_decision(
    *,
    previous_id: Optional[str],
    previous_score: Optional[float],
    evaluation: Optional[EvaluationResult],
    change: ContextChange,
    invalidated: List[str],
) -> Tuple[str, Optional[str], Optional[float], List[str], Optional[str]]:
    """
    Deterministic KEEP/SWITCH/… policy on top of Decision Engine scores.

    Returns:
      decision, effective_new_id, effective_new_score, factors, de_preferred_id
    """
    factors: List[str] = []
    scores = _score_map(evaluation)
    valid = _valid_ids(evaluation)
    de_preferred = (
        evaluation.recommended_route.route_id
        if evaluation and evaluation.recommended_route
        else None
    )
    de_score = scores.get(de_preferred) if de_preferred else None

    if not valid or de_preferred is None:
        factors.append("no_valid_candidates_after_reevaluation")
        return (
            ReplanDecision.NO_FEASIBLE_ALTERNATIVE.value,
            None,
            None,
            factors,
            de_preferred,
        )

    prev_still_valid = previous_id is not None and previous_id in valid
    if previous_id and previous_id in invalidated:
        prev_still_valid = False
        factors.append(f"previous_invalidated:{previous_id}")

    if not prev_still_valid:
        factors.append("previous_journey_invalid_or_missing")
        factors.append(f"switch_to:{de_preferred}")
        return (
            ReplanDecision.SWITCH_JOURNEY.value,
            de_preferred,
            de_score,
            factors,
            de_preferred,
        )

    prev_score_now = scores.get(previous_id)
    meaningful = _has_meaningful_context(change)
    tt_delta = abs(float(change.travel_time_delta_minutes or 0.0))
    if change.absolute_travel_time_minutes is not None and previous_score is not None:
        # absolute override — treat as significant if differs materially
        tt_delta = max(tt_delta, TRAVEL_TIME_SIGNIFICANT_MINUTES)

    if de_preferred == previous_id:
        if not meaningful or tt_delta <= TRAVEL_TIME_INSIGNIFICANT_MINUTES:
            factors.append("same_winner_no_meaningful_context")
            return (
                ReplanDecision.NO_SIGNIFICANT_CHANGE.value,
                previous_id,
                prev_score_now,
                factors,
                de_preferred,
            )
        factors.append("same_winner_after_significant_context")
        return (
            ReplanDecision.KEEP_CURRENT.value,
            previous_id,
            prev_score_now,
            factors,
            de_preferred,
        )

    # Decision Engine prefers a different journey while previous remains valid.
    margin = (de_score or 0.0) - (prev_score_now or 0.0)
    factors.append(
        f"de_prefers:{de_preferred} margin={margin:.2f} "
        f"threshold={SCORE_SWITCH_MARGIN}"
    )
    if margin >= SCORE_SWITCH_MARGIN:
        factors.append("switch_margin_met")
        return (
            ReplanDecision.SWITCH_JOURNEY.value,
            de_preferred,
            de_score,
            factors,
            de_preferred,
        )

    factors.append("switch_margin_not_met_keep_previous")
    decision = (
        ReplanDecision.NO_SIGNIFICANT_CHANGE.value
        if tt_delta <= TRAVEL_TIME_INSIGNIFICANT_MINUTES and not invalidated
        else ReplanDecision.KEEP_CURRENT.value
    )
    return decision, previous_id, prev_score_now, factors, de_preferred


def replan_commute(
    initial_request: CommuteRequest,
    initial_result: PlannerResult,
    context_change: ContextChange,
    *,
    api_key: Optional[str] = None,
    models_dir: str = "models",
    cache_ttl: Optional[int] = None,
    refresh_live_routes: bool = False,
    original_plan_id: Optional[str] = None,
    replan_request_id: Optional[str] = None,
) -> ReplanResult:
    """
    Re-evaluate an existing plan under a context change.

    Authority: deterministic evaluate_routes + named switch thresholds.
    Live refresh: optional plan_commute() when context_source == "live".
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

    req_id = replan_request_id or f"replan-{uuid.uuid4().hex[:12]}"
    provenance: List[str] = []
    previous_id = _recommended_id(initial_result)
    previous_scores = _score_map(initial_result.evaluation)
    previous_score = previous_scores.get(previous_id) if previous_id else None
    change_type = context_change.inferred_change_type()
    affected = [context_change.to_dict()]

    # --- Live refresh path ---
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
            preferences=_merge_preferences(
                initial_request.preferences, context_change
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
        decision, new_id, new_score, factors, de_pref = classify_replan_decision(
            previous_id=previous_id,
            previous_score=previous_score,
            evaluation=updated.evaluation,
            change=context_change,
            invalidated=list(context_change.invalidate_route_ids or []),
        )
        return ReplanResult(
            initial=initial_result,
            updated=updated,
            context_change=context_change,
            recommendation_changed=decision == ReplanDecision.SWITCH_JOURNEY.value,
            previous_route_id=previous_id,
            new_route_id=new_id,
            provenance_notes=provenance,
            decision=decision,
            previous_score=previous_score,
            new_score=new_score,
            invalidated_journey_ids=list(context_change.invalidate_route_ids or []),
            retained_journey_ids=_valid_ids(updated.evaluation),
            decision_factors=factors,
            replan_request_id=req_id,
            original_plan_id=original_plan_id,
            affected_context_changes=affected,
            decision_engine_preferred_id=de_pref,
            orchestration_metadata={
                "change_type": change_type,
                "context_source": context_change.context_source,
                "live_refresh": True,
            },
        )

    if initial_result.error and not initial_result.routes:
        raise InvalidReplanInput(
            f"Cannot replan from failed initial result: {initial_result.error}"
        )

    routes = _copy_routes(list(initial_result.routes or []))
    warnings = list(initial_result.warnings or [])
    data_sources = list(initial_result.data_sources or [])
    invalidated: List[str] = []

    if context_change.context_source == "none" and not _has_meaningful_context(
        context_change
    ):
        provenance.append("UNCHANGED_CONTEXT:re_evaluate_only")
        warnings.append("CONTEXT_UNCHANGED")
    elif context_change.context_source == "simulated":
        provenance.append("SIMULATED:demo_context_overlay")
        routes = _apply_simulated_overlays(
            routes, context_change, provenance, warnings
        )
        if context_change.weather_changed:
            warnings.append("WEATHER_CHANGED_SIMULATED (not used by scoring)")
            if context_change.weather_note:
                provenance.append(
                    f"SIMULATED:weather_note:{context_change.weather_note}"
                )
            # Do not fabricate weather penalties.
            provenance.append("WEATHER:no_fabricated_penalty")
        if "simulated_context" not in data_sources:
            data_sources.append("simulated_context")
    elif context_change.context_source == "live":
        provenance.append("LIVE:context_flag_without_candidate_refresh")
        warnings.append("LIVE_CONTEXT_NO_REFRESH")

    routes, invalidated = _invalidate_routes(
        routes,
        context_change.invalidate_route_ids,
        provenance,
        warnings,
    )

    if context_change.updated_departure_time and context_change.context_source != "live":
        warnings.append(
            f"DEPARTURE_TIME_UPDATED_IN_REQUEST ({context_change.updated_departure_time})"
        )

    preferences = _merge_preferences(initial_request.preferences, context_change)
    if context_change.excluded_modes_update is not None:
        provenance.append(
            f"CONSTRAINT_UPDATE:excluded_modes={context_change.excluded_modes_update}"
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
            decision=ReplanDecision.NO_FEASIBLE_ALTERNATIVE.value,
            previous_score=previous_score,
            invalidated_journey_ids=invalidated,
            replan_request_id=req_id,
            original_plan_id=original_plan_id,
            affected_context_changes=affected,
            decision_factors=["evaluator_failure"],
        )

    decision, new_id, new_score, factors, de_pref = classify_replan_decision(
        previous_id=previous_id,
        previous_score=previous_score,
        evaluation=evaluation,
        change=context_change,
        invalidated=invalidated,
    )

    # Align user-facing recommended_route with policy when threshold keeps previous.
    if (
        new_id
        and evaluation.recommended_route
        and evaluation.recommended_route.route_id != new_id
    ):
        kept = next((r for r in routes if r.route_id == new_id), None)
        if kept is not None:
            evaluation = replace(evaluation, recommended_route=kept)
            factors.append("aligned_recommended_route_to_policy_decision")
            # Refresh Top-5 so rank-1 matches the authoritative recommendation.
            evaluation = replace(
                evaluation,
                top_selection=select_top_journeys(
                    evaluation, preferences
                ).to_dict(),
            )
    new_request = initial_request
    if context_change.updated_departure_time or context_change.excluded_modes_update:
        new_request = replace(
            initial_request,
            departure_time=(
                context_change.updated_departure_time
                or initial_request.departure_time
            ),
            preferences=preferences,
        )

    updated = PlannerResult(
        request=new_request,
        routes=routes,
        evaluation=evaluation,
        data_sources=data_sources,
        historical_signal_used=initial_result.historical_signal_used,
        warnings=warnings,
    )

    retained = _valid_ids(evaluation)
    return ReplanResult(
        initial=initial_result,
        updated=updated,
        context_change=context_change,
        recommendation_changed=decision == ReplanDecision.SWITCH_JOURNEY.value,
        previous_route_id=previous_id,
        new_route_id=new_id,
        provenance_notes=provenance,
        decision=decision,
        previous_score=previous_score,
        new_score=new_score,
        invalidated_journey_ids=invalidated,
        retained_journey_ids=retained,
        decision_factors=factors,
        replan_request_id=req_id,
        original_plan_id=original_plan_id,
        affected_context_changes=affected,
        decision_engine_preferred_id=de_pref,
        orchestration_metadata={
            "change_type": change_type,
            "context_source": context_change.context_source,
            "candidates_reevaluated": len(routes),
            "score_switch_margin": SCORE_SWITCH_MARGIN,
            "live_or_simulated": context_change.context_source,
        },
    )
