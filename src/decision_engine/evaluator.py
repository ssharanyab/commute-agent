"""
Route Evaluator Module.

Orchestrates constraint validation, candidate metric normalization, weighted scoring,
and ranking to select the optimal commute option for the user's preferences.
"""

from typing import List, Optional

from src.decision_engine.models import (
    RouteCandidate,
    UserPreferences,
    ScoredRoute,
    EvaluationResult,
)
from src.decision_engine.scoring import (
    validate_hard_constraints,
    normalize_candidate_pool,
    calculate_route_utility,
    generate_reason_codes,
    build_route_categories,
)


def evaluate_routes(
    candidates: List[RouteCandidate],
    preferences: Optional[UserPreferences] = None,
) -> EvaluationResult:
    """Evaluate, rank, and recommend the optimal commute route candidate.

    Authority: deterministic scoring only. Hard-constraint violators are never
    recommended. Missing historical coverage does not invalidate a route.
    """
    if preferences is None:
        preferences = UserPreferences()

    if not candidates:
        return EvaluationResult(
            recommended_route=None,
            ranked_routes=[],
            score=0.0,
            reason_codes=[],
            constraint_violations=[],
            route_categories=[],
        )

    norm_pool = normalize_candidate_pool(candidates)
    scored_routes: List[ScoredRoute] = []

    for candidate in candidates:
        violations = validate_hard_constraints(candidate, preferences)
        norm_metrics = norm_pool.get(candidate.route_id, {})

        score, sub_scores = calculate_route_utility(
            candidate, norm_metrics, preferences, violations
        )
        reason_codes = generate_reason_codes(
            candidate, candidates, norm_metrics, preferences, violations
        )

        scored_routes.append(
            ScoredRoute(
                route=candidate,
                final_score=score,
                normalized_metrics=norm_metrics,
                sub_scores=sub_scores,
                reason_codes=reason_codes,
                constraint_violations=violations,
                is_valid=len(violations) == 0,
            )
        )

    ranked_routes = sorted(
        scored_routes, key=lambda sr: (-sr.final_score, sr.route.route_id)
    )

    valid_ranked = [sr for sr in ranked_routes if sr.is_valid]
    all_violations: List[str] = []
    for sr in ranked_routes:
        all_violations.extend(sr.constraint_violations)
    all_violations = list(dict.fromkeys(all_violations))

    if valid_ranked:
        chosen = valid_ranked[0]
        categories = build_route_categories(valid_ranked, chosen)
        return EvaluationResult(
            recommended_route=chosen.route,
            ranked_routes=ranked_routes,
            score=chosen.final_score,
            reason_codes=list(chosen.reason_codes),
            constraint_violations=[],
            route_categories=categories,
        )

    top_scored = ranked_routes[0]
    return EvaluationResult(
        recommended_route=None,
        ranked_routes=ranked_routes,
        score=top_scored.final_score,
        reason_codes=["NO_VALID_ROUTE"],
        constraint_violations=all_violations,
        route_categories=[],
    )
