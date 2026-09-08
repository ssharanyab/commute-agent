"""Personalization / constraints capability."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.agent.capabilities import PersonalizationResult
from src.decision_engine.models import UserPreferences
from src.journey_builder.constraints import JourneyConstraints, SearchLimits


def resolve_personalization(
    *,
    preferences: Optional[UserPreferences] = None,
    max_transfers: Optional[int] = None,
    stored_preferences_fn=None,
    user_id: str = "",
) -> PersonalizationResult:
    """
    Explicit request preferences take precedence.

    Stored profiles are never invented — if unavailable, source=request|default.
    """
    stored_available = False
    if stored_preferences_fn is not None:
        stored = stored_preferences_fn(user_id)
        stored_available = bool(
            isinstance(stored, dict) and stored.get("available")
        )

    prefs = preferences or UserPreferences()
    source = "request" if preferences is not None else "default"
    return PersonalizationResult(
        excluded_modes=list(prefs.excluded_modes) if prefs.excluded_modes else None,
        max_walking_minutes=prefs.max_walking_minutes,
        max_transfers=max_transfers,
        preference_profile=None,
        preferences=prefs.to_dict(),
        source=source,
        stored_profile_available=stored_available,
    )


def to_journey_constraints(
    personalization: PersonalizationResult,
    *,
    walk_speed_m_per_min: float = 80.0,
) -> JourneyConstraints:
    max_walk_m = None
    if personalization.max_walking_minutes is not None:
        max_walk_m = float(personalization.max_walking_minutes) * walk_speed_m_per_min
    return JourneyConstraints(
        excluded_modes=personalization.excluded_modes,
        max_walking_meters=max_walk_m,
    )


def apply_transfer_limit(
    limits: SearchLimits, personalization: PersonalizationResult
) -> SearchLimits:
    if personalization.max_transfers is None:
        return limits
    return SearchLimits(
        max_walking_access_meters=limits.max_walking_access_meters,
        max_walking_egress_meters=limits.max_walking_egress_meters,
        max_walk_transfer_meters=limits.max_walk_transfer_meters,
        max_direct_walk_meters=limits.max_direct_walk_meters,
        max_road_access_meters=limits.max_road_access_meters,
        max_transfers=int(personalization.max_transfers),
        max_legs=limits.max_legs,
        max_candidates=limits.max_candidates,
        max_nodes_explored=limits.max_nodes_explored,
        allow_road_access=limits.allow_road_access,
        road_access_modes=limits.road_access_modes,
    )
