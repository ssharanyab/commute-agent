"""
Data models for the commute planning orchestrator.

Reuses RouteCandidate, UserPreferences, and EvaluationResult from the
decision engine. Does not duplicate scoring or mobility types.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Union

from src.decision_engine.models import RouteCandidate, UserPreferences, EvaluationResult
from src.mobility.models import TravelMode


class ReplanDecision(str, Enum):
    """Deterministic adaptive-loop outcome. Never assigned by Gemini."""

    KEEP_CURRENT = "KEEP_CURRENT"
    SWITCH_JOURNEY = "SWITCH_JOURNEY"
    NO_FEASIBLE_ALTERNATIVE = "NO_FEASIBLE_ALTERNATIVE"
    NO_SIGNIFICANT_CHANGE = "NO_SIGNIFICANT_CHANGE"


class ContextChangeType(str, Enum):
    TRAFFIC_CHANGE = "TRAFFIC_CHANGE"
    WEATHER_CHANGE = "WEATHER_CHANGE"
    TRANSIT_DISRUPTION = "TRANSIT_DISRUPTION"
    USER_CONSTRAINT_CHANGE = "USER_CONSTRAINT_CHANGE"
    JOURNEY_DELAY = "JOURNEY_DELAY"
    OTHER_CONTEXT_CHANGE = "OTHER_CONTEXT_CHANGE"
    NONE = "NONE"


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
    """Structured context delta for adaptive replanning.

    Simulated overlays never pretend to be live Google Maps data.
    Prefer change_type + typed fields over free-form text as the primary signal.
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
    # Phase 5E structured fields
    change_type: str = ContextChangeType.NONE.value
    affected_leg_id: Optional[str] = None
    previous_value: Optional[Any] = None
    new_value: Optional[Any] = None
    confidence: Optional[float] = None
    change_timestamp: Optional[str] = None
    requires_reevaluation: bool = True
    # Absolute travel time override for target route (simulation-friendly)
    absolute_travel_time_minutes: Optional[float] = None
    # Hard-invalidate these journey/route IDs (e.g. transit disruption)
    invalidate_route_ids: Optional[List[str]] = None
    # Merge into request preferences for replan (constraint change)
    excluded_modes_update: Optional[List[str]] = None
    max_walking_minutes_update: Optional[float] = None

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
            "change_type": self.change_type,
            "affected_leg_id": self.affected_leg_id,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "confidence": self.confidence,
            "change_timestamp": self.change_timestamp,
            "requires_reevaluation": self.requires_reevaluation,
            "absolute_travel_time_minutes": self.absolute_travel_time_minutes,
            "invalidate_route_ids": list(self.invalidate_route_ids)
            if self.invalidate_route_ids
            else None,
            "excluded_modes_update": list(self.excluded_modes_update)
            if self.excluded_modes_update
            else None,
            "max_walking_minutes_update": self.max_walking_minutes_update,
        }

    def inferred_change_type(self) -> str:
        if self.change_type and self.change_type != ContextChangeType.NONE.value:
            return self.change_type
        if self.excluded_modes_update is not None or self.max_walking_minutes_update is not None:
            return ContextChangeType.USER_CONSTRAINT_CHANGE.value
        if self.invalidate_route_ids:
            return ContextChangeType.TRANSIT_DISRUPTION.value
        if self.traffic_changed or self.travel_time_delta_minutes or (
            self.absolute_travel_time_minutes is not None
        ):
            return ContextChangeType.TRAFFIC_CHANGE.value
        if self.disruption_changed:
            return ContextChangeType.TRANSIT_DISRUPTION.value
        if self.weather_changed:
            return ContextChangeType.WEATHER_CHANGE.value
        return ContextChangeType.NONE.value


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
    # Phase 5E adaptive classification
    decision: Optional[str] = None
    previous_score: Optional[float] = None
    new_score: Optional[float] = None
    invalidated_journey_ids: List[str] = field(default_factory=list)
    retained_journey_ids: List[str] = field(default_factory=list)
    decision_factors: List[str] = field(default_factory=list)
    replan_request_id: Optional[str] = None
    original_plan_id: Optional[str] = None
    affected_context_changes: List[Dict[str, Any]] = field(default_factory=list)
    orchestration_metadata: Dict[str, Any] = field(default_factory=dict)
    decision_engine_preferred_id: Optional[str] = None

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
            "decision": self.decision,
            "previous_score": self.previous_score,
            "new_score": self.new_score,
            "invalidated_journey_ids": list(self.invalidated_journey_ids),
            "retained_journey_ids": list(self.retained_journey_ids),
            "decision_factors": list(self.decision_factors),
            "replan_request_id": self.replan_request_id,
            "original_plan_id": self.original_plan_id,
            "affected_context_changes": list(self.affected_context_changes),
            "orchestration_metadata": dict(self.orchestration_metadata),
            "decision_engine_preferred_id": self.decision_engine_preferred_id,
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
