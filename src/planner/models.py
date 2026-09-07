"""
Data models for the commute planning orchestrator.

Reuses RouteCandidate, UserPreferences, and EvaluationResult from the
decision engine. Does not duplicate scoring or mobility types.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union

from src.decision_engine.models import RouteCandidate, UserPreferences, EvaluationResult
from src.mobility.models import TravelMode


@dataclass
class CommuteRequest:
    """Application-level commute planning request."""
    user_id: str
    origin: str
    destination: str
    departure_time: Optional[str] = None
    objective: Optional[str] = None  # Informational only; scoring uses preferences.
    preferences: Optional[UserPreferences] = None
    origin_zone: Optional[int] = None
    destination_zone: Optional[int] = None
    modes: Optional[List[Union[str, TravelMode]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "origin": self.origin,
            "destination": self.destination,
            "departure_time": self.departure_time,
            "objective": self.objective,
            "preferences": self.preferences.to_dict() if self.preferences else None,
            "origin_zone": self.origin_zone,
            "destination_zone": self.destination_zone,
            "modes": [
                m.value if isinstance(m, TravelMode) else m
                for m in self.modes
            ] if self.modes else None,
        }


@dataclass
class PlannerResult:
    """Structured output of a commute planning run."""
    request: CommuteRequest
    routes: List[RouteCandidate]
    evaluation: Optional[EvaluationResult]
    data_sources: List[str] = field(default_factory=list)
    historical_signal_used: bool = False
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    error_detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "routes": [r.to_dict() for r in self.routes],
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "data_sources": list(self.data_sources),
            "historical_signal_used": self.historical_signal_used,
            "warnings": list(self.warnings),
            "error": self.error,
            "error_detail": self.error_detail,
        }


class PlannerError(Exception):
    """Base error for commute planner orchestration failures."""
    pass


class InvalidCommuteRequest(PlannerError):
    """Raised when a CommuteRequest fails validation."""
    pass
