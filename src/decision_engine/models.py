"""
Data Models for Route Evaluation Engine.

Defines strongly typed structures for route candidates, user preferences,
scored route outputs, and overall evaluation results.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert candidate to dictionary serialization."""
        return {
            "route_id": self.route_id,
            "mode": self.mode,
            "travel_time_minutes": self.travel_time_minutes,
            "cost": self.cost,
            "walking_minutes": self.walking_minutes,
            "transfers": self.transfers,
            "congestion_score": self.congestion_score,
            "reliability_score": self.reliability_score,
            "disruption_risk": self.disruption_risk,
            "historical_mobility_signal": self.historical_mobility_signal
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
            "max_walking_minutes": self.max_walking_minutes,
            "max_cost": self.max_cost,
            "avoid_heavy_traffic": self.avoid_heavy_traffic
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation result to dictionary serialization."""
        return {
            "recommended_route": self.recommended_route.to_dict() if self.recommended_route else None,
            "ranked_routes": [r.to_dict() for r in self.ranked_routes],
            "score": round(self.score, 2),
            "reason_codes": self.reason_codes,
            "constraint_violations": self.constraint_violations
        }
