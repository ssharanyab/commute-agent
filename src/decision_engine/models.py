"""
Data Models for Route Evaluation Engine.

Defines strongly typed structures for route candidates, user preferences,
scored route outputs, and overall evaluation results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


# ---------------------------------------------------------------------------
# Named preference profiles (soft weights — not hard mode locks)
# ---------------------------------------------------------------------------
PROFILE_FASTEST = "FASTEST"
PROFILE_CHEAPEST = "CHEAPEST"
PROFILE_LOW_WALKING = "LOW_WALKING"
PROFILE_RELIABLE = "RELIABLE"
PROFILE_LOW_TRAFFIC = "LOW_TRAFFIC"
PROFILE_BALANCED = "BALANCED"

# Alternative category labels
CATEGORY_BEST_OVERALL = "BEST_OVERALL"
CATEGORY_FASTEST = "FASTEST"
CATEGORY_CHEAPEST = "CHEAPEST"
CATEGORY_MOST_RELIABLE = "MOST_RELIABLE"


@dataclass
class RouteCandidate:
    """Strongly typed model representing a candidate commute route."""
    route_id: str
    mode: str  # e.g., 'cab', 'bus', 'metro', 'auto', 'walking', 'hybrid'
    travel_time_minutes: float
    cost: float
    walking_minutes: float
    transfers: int
    congestion_score: float  # 0.0 (free flow) to 1.0 (heavy congestion)
    reliability_score: float  # 0.0 (unreliable) to 1.0 (highly reliable)
    disruption_risk: float  # 0.0 (low risk) to 1.0 (high disruption risk)
    historical_mobility_signal: Optional[Dict[str, Any]] = None
    # Google Routes API geometry / identity (optional; fixtures may omit)
    google_polyline: Optional[str] = None
    google_route_token: Optional[str] = None
    distance_meters: Optional[int] = None  # Google-provided when adapted from Maps
    # Segment modes for hard exclusion across the full journey (not scoring).
    component_modes: Optional[List[str]] = None
    # Phase 6E: explicit known/unknown — never treat unknown cost as free.
    cost_status: str = "known"  # known | unknown | unavailable
    duration_status: str = "known"  # known | unknown | unavailable
    partial_known_cost_inr: Optional[float] = None
    mode_signature: str = ""
    access_walking_meters: Optional[float] = None
    transfer_walking_meters: Optional[float] = None
    egress_walking_meters: Optional[float] = None
    # Complete-journey walking meters when known (Phase 7B hard constraint).
    walking_distance_meters: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert candidate to dictionary serialization."""
        return {
            "route_id": self.route_id,
            "mode": self.mode,
            "travel_time_minutes": self.travel_time_minutes,
            "cost": self.cost,
            "cost_status": self.cost_status,
            "duration_status": self.duration_status,
            "partial_known_cost_inr": self.partial_known_cost_inr,
            "walking_minutes": self.walking_minutes,
            "transfers": self.transfers,
            "congestion_score": self.congestion_score,
            "reliability_score": self.reliability_score,
            "disruption_risk": self.disruption_risk,
            "historical_mobility_signal": self.historical_mobility_signal,
            "google_polyline": self.google_polyline,
            "google_route_token": self.google_route_token,
            "distance_meters": self.distance_meters,
            "component_modes": list(self.component_modes) if self.component_modes else None,
            "mode_signature": self.mode_signature,
            "access_walking_meters": self.access_walking_meters,
            "transfer_walking_meters": self.transfer_walking_meters,
            "egress_walking_meters": self.egress_walking_meters,
            "walking_distance_meters": self.walking_distance_meters,
        }


@dataclass
class UserPreferences:
    """Strongly typed model representing user trade-off preferences and hard constraints."""
    time_weight: float = 1.0
    cost_weight: float = 1.0
    walking_weight: float = 1.0
    transfer_weight: float = 1.0
    congestion_weight: float = 1.0
    reliability_weight: float = 1.0
    preferred_modes: Optional[List[str]] = None
    excluded_modes: Optional[List[str]] = None
    max_walking_minutes: Optional[float] = None
    max_cost: Optional[float] = None
    avoid_heavy_traffic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert preferences to dictionary serialization."""
        return {
            "time_weight": self.time_weight,
            "cost_weight": self.cost_weight,
            "walking_weight": self.walking_weight,
            "transfer_weight": self.transfer_weight,
            "congestion_weight": self.congestion_weight,
            "reliability_weight": self.reliability_weight,
            "preferred_modes": self.preferred_modes,
            "excluded_modes": list(self.excluded_modes) if self.excluded_modes else None,
            "max_walking_minutes": self.max_walking_minutes,
            "max_cost": self.max_cost,
            "avoid_heavy_traffic": self.avoid_heavy_traffic
        }


def preference_profile(name: str, **overrides: Any) -> UserPreferences:
    """Build UserPreferences from a named profile.

    Profiles only set soft trade-off weights. Hard constraints (excluded_modes,
    max_cost, max_walking, avoid_heavy_traffic) must be supplied via overrides
    or mutated by the caller.
    """
    key = (name or PROFILE_BALANCED).strip().upper().replace("-", "_").replace(" ", "_")
    base: Dict[str, float]
    if key == PROFILE_FASTEST:
        base = dict(
            time_weight=8.0,
            cost_weight=1.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=1.0,
            reliability_weight=1.0,
        )
    elif key == PROFILE_CHEAPEST:
        base = dict(
            time_weight=1.0,
            cost_weight=8.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=1.0,
            reliability_weight=1.0,
        )
    elif key == PROFILE_LOW_WALKING:
        base = dict(
            time_weight=1.0,
            cost_weight=1.0,
            walking_weight=8.0,
            transfer_weight=1.0,
            congestion_weight=1.0,
            reliability_weight=1.0,
        )
    elif key == PROFILE_RELIABLE:
        base = dict(
            time_weight=1.0,
            cost_weight=1.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=1.0,
            reliability_weight=8.0,
        )
    elif key == PROFILE_LOW_TRAFFIC:
        base = dict(
            time_weight=1.0,
            cost_weight=1.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=8.0,
            reliability_weight=1.0,
        )
    else:
        base = dict(
            time_weight=1.0,
            cost_weight=1.0,
            walking_weight=1.0,
            transfer_weight=1.0,
            congestion_weight=1.0,
            reliability_weight=1.0,
        )
    base.update(overrides)
    return UserPreferences(**base)


@dataclass
class RouteCategory:
    """Labeled alternative derived from actual candidate attributes."""
    category: str
    route: RouteCandidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "route_id": self.route.route_id,
            "route": self.route.to_dict(),
        }


@dataclass
class ScoredRoute:
    """Model representing an evaluated candidate route with scores and reason codes."""
    route: RouteCandidate
    final_score: float
    normalized_metrics: Dict[str, float] = field(default_factory=dict)
    sub_scores: Dict[str, float] = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)
    constraint_violations: List[str] = field(default_factory=list)
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert scored route to dictionary serialization."""
        return {
            "route": self.route.to_dict(),
            "final_score": round(self.final_score, 2),
            "normalized_metrics": {k: round(v, 4) for k, v in self.normalized_metrics.items()},
            "sub_scores": {k: round(v, 2) for k, v in self.sub_scores.items()},
            "reason_codes": self.reason_codes,
            "constraint_violations": self.constraint_violations,
            "is_valid": self.is_valid
        }


@dataclass
class EvaluationResult:
    """Final output structure from the Route Evaluation Engine."""
    recommended_route: Optional[RouteCandidate]
    ranked_routes: List[ScoredRoute]
    score: float
    reason_codes: List[str] = field(default_factory=list)
    constraint_violations: List[str] = field(default_factory=list)
    # Category winners (deduplicated route list separately in alternatives sense)
    route_categories: List[RouteCategory] = field(default_factory=list)
    # Phase 7B structured strategy / constraint diagnostics (not user-facing copy).
    strategy_meta: Optional[Dict[str, Any]] = None
    # Phase 7C: diverse Top-5 presentation layer (does not change recommended_route).
    top_selection: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation result to dictionary serialization."""
        return {
            "recommended_route": self.recommended_route.to_dict() if self.recommended_route else None,
            "ranked_routes": [r.to_dict() for r in self.ranked_routes],
            "score": round(self.score, 2),
            "reason_codes": self.reason_codes,
            "constraint_violations": self.constraint_violations,
            "route_categories": [c.to_dict() for c in self.route_categories],
            "strategy_meta": dict(self.strategy_meta) if self.strategy_meta else None,
            "top_selection": dict(self.top_selection) if self.top_selection else None,
        }
