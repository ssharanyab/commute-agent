"""
Route Evaluator Module.

Orchestrates constraint validation, candidate metric normalization, weighted scoring,
and ranking to select the optimal commute option.
"""

from typing import List, Optional
from src.decision_engine.models import RouteCandidate, UserPreferences, ScoredRoute, EvaluationResult
from src.decision_engine.scoring import (
    validate_hard_constraints,
    normalize_candidate_pool,
    calculate_route_utility,
    generate_reason_codes
)


def evaluate_routes(candidates: List[RouteCandidate], preferences: Optional[UserPreferences] = None) -> EvaluationResult:
    """Evaluate, rank, and recommend the optimal commute route candidate.
    
    Args:
        candidates (List[RouteCandidate]): List of candidate routes.
        preferences (Optional[UserPreferences]): User preferences and constraints.
        
    Returns:
        EvaluationResult: Evaluation result containing top recommendation, ranked routes,
                          scores, reason codes, and constraint violations.
    """
    if preferences is None:
        preferences = UserPreferences()

    if not candidates:
        return EvaluationResult(
            recommended_route=None,
            ranked_routes=[],
            score=0.0,
            reason_codes=[],
            constraint_violations=[]
        )

    # 1. Normalize metrics across candidate pool
    norm_pool = normalize_candidate_pool(candidates)

    scored_routes: List[ScoredRoute] = []

    # 2. Evaluate each candidate
    for candidate in candidates:
        violations = validate_hard_constraints(candidate, preferences)
        norm_metrics = norm_pool.get(candidate.route_id, {})
        
        score, sub_scores = calculate_route_utility(candidate, norm_metrics, preferences, violations)
        reason_codes = generate_reason_codes(candidate, candidates, norm_metrics, preferences, violations)

        scored_routes.append(
            ScoredRoute(
                route=candidate,
                final_score=score,
                normalized_metrics=norm_metrics,
                sub_scores=sub_scores,
                reason_codes=reason_codes,
                constraint_violations=violations,
                is_valid=len(violations) == 0
            )
        )

    # 3. Sort routes deterministically: descending final_score, then ascending route_id
    ranked_routes = sorted(scored_routes, key=lambda sr: (-sr.final_score, sr.route.route_id))

    # 4. Select top recommendation
    top_scored = ranked_routes[0]
    
    # If top route is valid, recommend it; if all routes violate constraints, select highest score valid or top
    recommended = top_scored.route if top_scored.is_valid else None
    
    all_violations = []
    for sr in ranked_routes:
        all_violations.extend(sr.constraint_violations)
    all_violations = list(dict.fromkeys(all_violations))

    return EvaluationResult(
        recommended_route=recommended,
        ranked_routes=ranked_routes,
        score=top_scored.final_score,
        reason_codes=top_scored.reason_codes,
        constraint_violations=top_scored.constraint_violations if not top_scored.is_valid else []
    )
