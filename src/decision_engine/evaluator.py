"""
Route Evaluator Module.

Orchestrates constraint validation, candidate metric normalization, weighted scoring,
and ranking to select the optimal commute option for the user's preferences.

Phase 7B: optional strategy + MobilityConstraints apply as hard filters and
lexicographic tiers *before* preference scoring — never as giant score bonuses.
"""

from __future__ import annotations

from typing import List, Optional

from src.agent.mobility_strategy import MobilityConstraints, MobilityStrategy
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
from src.decision_engine.strategy import (
    StrategyEvaluationMeta,
    classify_backbone,
    strategy_tier_key,
    validate_mobility_constraints,
)
from src.decision_engine.top5 import select_top_journeys


def evaluate_routes(
    candidates: List[RouteCandidate],
    preferences: Optional[UserPreferences] = None,
    *,
    strategy: Optional[MobilityStrategy] = None,
    constraints: Optional[MobilityConstraints] = None,
) -> EvaluationResult:
    """Evaluate, rank, and recommend the optimal commute route candidate.

    Authority: deterministic scoring only. Hard-constraint violators are never
    recommended. Missing historical coverage does not invalidate a route.

    When ``strategy`` / ``constraints`` are unset, behavior matches Phase 6F/6G.
    """
    if preferences is None:
        preferences = UserPreferences()

    strategy_meta = StrategyEvaluationMeta(
        strategy_applied=strategy.value if strategy is not None else None,
    )

    if not candidates:
        empty = EvaluationResult(
            recommended_route=None,
            ranked_routes=[],
            score=0.0,
            reason_codes=[],
            constraint_violations=[],
            route_categories=[],
            strategy_meta=strategy_meta.to_dict(),
        )
        empty.top_selection = select_top_journeys(
            empty, preferences, strategy=strategy
        ).to_dict()
        return empty

    norm_pool = normalize_candidate_pool(candidates)
    scored_routes: List[ScoredRoute] = []

    for candidate in candidates:
        backbone = classify_backbone(candidate)
        strategy_meta.backbone_by_route_id[candidate.route_id] = backbone.value

        violations = list(validate_hard_constraints(candidate, preferences))
        mobility_violations = validate_mobility_constraints(
            candidate,
            strategy=strategy,
            constraints=constraints,
        )
        for code in mobility_violations:
            if code not in violations:
                violations.append(code)

        if violations:
            strategy_meta.constraint_rejections.append(
                {
                    "route_id": candidate.route_id,
                    "reasons": list(violations),
                    "backbone": backbone.value,
                }
            )

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

    # Preference score order (existing behavior), then strategy tier among valid.
    ranked_routes = sorted(
        scored_routes, key=lambda sr: (-sr.final_score, sr.route.route_id)
    )

    valid_ranked = [sr for sr in ranked_routes if sr.is_valid]
    strategy_meta.strategy_eligible_route_ids = [
        sr.route.route_id for sr in valid_ranked
    ]

    all_violations: List[str] = []
    for sr in ranked_routes:
        all_violations.extend(sr.constraint_violations)
    all_violations = list(dict.fromkeys(all_violations))

    if valid_ranked:
        # Lexicographic: best strategy tier, then existing preference score.
        tiered = sorted(
            valid_ranked,
            key=lambda sr: (
                strategy_tier_key(sr.route, strategy),
                -sr.final_score,
                sr.route.route_id,
            ),
        )
        best_tier = strategy_tier_key(tiered[0].route, strategy)
        strategy_pool = [
            sr
            for sr in tiered
            if strategy_tier_key(sr.route, strategy) == best_tier
        ]
        strategy_meta.strategy_tier_route_ids = [
            sr.route.route_id for sr in strategy_pool
        ]
        chosen = strategy_pool[0]
        categories = build_route_categories(strategy_pool, chosen)
        result = EvaluationResult(
            recommended_route=chosen.route,
            ranked_routes=ranked_routes,
            score=chosen.final_score,
            reason_codes=list(chosen.reason_codes),
            constraint_violations=[],
            route_categories=categories,
            strategy_meta=strategy_meta.to_dict(),
        )
        result.top_selection = select_top_journeys(
            result, preferences, strategy=strategy
        ).to_dict()
        return result

    top_scored = ranked_routes[0]
    result = EvaluationResult(
        recommended_route=None,
        ranked_routes=ranked_routes,
        score=top_scored.final_score,
        reason_codes=["NO_VALID_ROUTE"],
        constraint_violations=all_violations,
        route_categories=[],
        strategy_meta=strategy_meta.to_dict(),
    )
    result.top_selection = select_top_journeys(
        result, preferences, strategy=strategy
    ).to_dict()
    return result
