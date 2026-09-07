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


@dataclass
class ContextChange:
    """Minimal structured context delta for adaptive replanning.

    Simulated overlays never pretend to be live Google Maps data.
    """
    traffic_changed: bool = False
    disruption_changed: bool = False
    weather_changed: bool = False
    updated_departure_time: Optional[str] = None
    # "none" | "live" | "simulated"
    context_source: str = "none"
    # Simulated route overlays (route_id -> delta). Explicitly demo/simulated.
    target_route_id: Optional[str] = None
    congestion_delta: float = 0.0
    travel_time_delta_minutes: float = 0.0
    disruption_delta: float = 0.0
    weather_note: Optional[str] = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "traffic_changed": self.traffic_changed,
            "disruption_changed": self.disruption_changed,
            "weather_changed": self.weather_changed,
            "updated_departure_time": self.updated_departure_time,
            "context_source": self.context_source,
            "target_route_id": self.target_route_id,
            "congestion_delta": self.congestion_delta,
            "travel_time_delta_minutes": self.travel_time_delta_minutes,
            "disruption_delta": self.disruption_delta,
            "weather_note": self.weather_note,
            "description": self.description,
        }


@dataclass
class ReplanResult:
    """Before/after deterministic replan payload."""
    initial: PlannerResult
    updated: PlannerResult
    context_change: ContextChange
    recommendation_changed: bool
    previous_route_id: Optional[str]
    new_route_id: Optional[str]
    provenance_notes: List[str] = field(default_factory=list)
    explanation: str = ""
    gemini_invoked: bool = False
    gemini_available: bool = False
    adk_invoked: bool = False
    mode: str = "deterministic_fallback"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial": self.initial.to_dict(),
            "updated": self.updated.to_dict(),
            "context_change": self.context_change.to_dict(),
            "recommendation_changed": self.recommendation_changed,
            "previous_route_id": self.previous_route_id,
            "new_route_id": self.new_route_id,
            "provenance_notes": list(self.provenance_notes),
            "explanation": self.explanation,
            "gemini_invoked": self.gemini_invoked,
            "gemini_available": self.gemini_available,
            "adk_invoked": self.adk_invoked,
            "mode": self.mode,
            "error": self.error,
        }


class PlannerError(Exception):
    """Base error for commute planner orchestration failures."""
    pass


class InvalidCommuteRequest(PlannerError):
    """Raised when a CommuteRequest fails validation."""
    pass


class InvalidReplanInput(PlannerError):
    """Raised when replanning inputs are malformed."""
    pass
