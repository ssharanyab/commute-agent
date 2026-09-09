"""
Route Evaluation Engine Package.

Provides deterministic candidate route evaluation, constraint validation,
weighted utility scoring, and human-readable reasoning for commute choices.
"""

from src.decision_engine.models import (
    RouteCandidate,
    UserPreferences,
    ScoredRoute,
    EvaluationResult,
    RouteCategory,
    preference_profile,
    PROFILE_FASTEST,
    PROFILE_CHEAPEST,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    PROFILE_LOW_TRAFFIC,
    PROFILE_BALANCED,
    CATEGORY_BEST_OVERALL,
    CATEGORY_FASTEST,
    CATEGORY_CHEAPEST,
    CATEGORY_MOST_RELIABLE,
)
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.top5 import (
    MAX_TOP_JOURNEYS,
    TopJourneyOption,
    TopJourneySelection,
    diversity_signature,
    select_top_journeys,
)

__all__ = [
    "RouteCandidate",
    "UserPreferences",
    "ScoredRoute",
    "EvaluationResult",
    "RouteCategory",
    "evaluate_routes",
    "preference_profile",
    "PROFILE_FASTEST",
    "PROFILE_CHEAPEST",
    "PROFILE_LOW_WALKING",
    "PROFILE_RELIABLE",
    "PROFILE_LOW_TRAFFIC",
    "PROFILE_BALANCED",
    "CATEGORY_BEST_OVERALL",
    "CATEGORY_FASTEST",
    "CATEGORY_CHEAPEST",
    "CATEGORY_MOST_RELIABLE",
    "MAX_TOP_JOURNEYS",
    "TopJourneyOption",
    "TopJourneySelection",
    "diversity_signature",
    "select_top_journeys",
]
