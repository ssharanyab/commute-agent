"""
Typed schemas for the ADK/Gemini reasoning layer.

AgentRecommendation metrics are always derived from PlannerResult.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from src.decision_engine.models import RouteCandidate, UserPreferences
from src.planner.models import CommuteRequest, PlannerResult


@dataclass
class AgentCommuteRequest:
    """Natural-language or structured commute request for the agent layer."""
    user_id: str
    origin: str
    destination: str
    departure_time: Optional[str] = None
    arrival_deadline: Optional[str] = None
    objective: Optional[str] = None
    preferences: Optional[UserPreferences] = None
    origin_zone: Optional[int] = None
    destination_zone: Optional[int] = None
    modes: Optional[List[str]] = None
    raw_text: Optional[str] = None

    def to_commute_request(self) -> CommuteRequest:
        return CommuteRequest(
            user_id=self.user_id,
            origin=self.origin,
            destination=self.destination,
            departure_time=self.departure_time,
            objective=self.objective,
            preferences=self.preferences,
            origin_zone=self.origin_zone,
            destination_zone=self.destination_zone,
            modes=self.modes,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "origin": self.origin,
            "destination": self.destination,
            "departure_time": self.departure_time,
            "arrival_deadline": self.arrival_deadline,
            "objective": self.objective,
            "preferences": self.preferences.to_dict() if self.preferences else None,
            "origin_zone": self.origin_zone,
            "destination_zone": self.destination_zone,
            "modes": list(self.modes) if self.modes else None,
            "raw_text": self.raw_text,
        }


@dataclass
class AgentRecommendation:
    """Grounded recommendation derived from PlannerResult."""
    recommended_route: Optional[RouteCandidate]
    alternatives: List[RouteCandidate]
    estimated_time: Optional[float]
    estimated_cost: Optional[float]
    walking_time: Optional[float]
    transfers: Optional[int]
    reliability: Optional[float]
    traffic: Optional[float]
    explanation: str
    reason_codes: List[str]
    data_sources: List[str]
    historical_signal_used: bool
    replanning_available: bool
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_route": self.recommended_route.to_dict() if self.recommended_route else None,
            "alternatives": [r.to_dict() for r in self.alternatives],
            "estimated_time": self.estimated_time,
            "estimated_cost": self.estimated_cost,
            "walking_time": self.walking_time,
            "transfers": self.transfers,
            "reliability": self.reliability,
            "traffic": self.traffic,
            "explanation": self.explanation,
            "reason_codes": list(self.reason_codes),
            "data_sources": list(self.data_sources),
            "historical_signal_used": self.historical_signal_used,
            "replanning_available": self.replanning_available,
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass
class AgentRunResult:
    """Full agent run payload for tests and demos."""
    recommendation: AgentRecommendation
    parsed_intent: Dict[str, Any]
    commute_request: Optional[CommuteRequest]
    planner_result: Optional[PlannerResult]
    tools_selected: List[str]
    gemini_available: bool
    gemini_invoked: bool
    adk_invoked: bool
    mode: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation": self.recommendation.to_dict(),
            "parsed_intent": dict(self.parsed_intent),
            "commute_request": self.commute_request.to_dict() if self.commute_request else None,
            "planner_result": self.planner_result.to_dict() if self.planner_result else None,
            "tools_selected": list(self.tools_selected),
            "gemini_available": self.gemini_available,
            "gemini_invoked": self.gemini_invoked,
            "adk_invoked": self.adk_invoked,
            "mode": self.mode,
        }


def recommendation_from_planner(
    planner_result: PlannerResult,
    explanation: str,
) -> AgentRecommendation:
    """Build AgentRecommendation strictly from PlannerResult.

    Any explanation text is attached as-is; metrics never come from Gemini.
    """
    evaluation = planner_result.evaluation
    recommended = evaluation.recommended_route if evaluation else None
    alternatives: List[RouteCandidate] = []
    reason_codes: List[str] = []
    if evaluation:
        reason_codes = list(evaluation.reason_codes)
        for scored in evaluation.ranked_routes:
            if recommended is None or scored.route.route_id != recommended.route_id:
                alternatives.append(scored.route)

    return AgentRecommendation(
        recommended_route=recommended,
        alternatives=alternatives,
        estimated_time=recommended.travel_time_minutes if recommended else None,
        estimated_cost=recommended.cost if recommended else None,
        walking_time=recommended.walking_minutes if recommended else None,
        transfers=recommended.transfers if recommended else None,
        reliability=recommended.reliability_score if recommended else None,
        traffic=recommended.congestion_score if recommended else None,
        explanation=explanation,
        reason_codes=reason_codes,
        data_sources=list(planner_result.data_sources),
        historical_signal_used=bool(planner_result.historical_signal_used),
        replanning_available=planner_result.error is None and recommended is not None,
        warnings=list(planner_result.warnings),
        error=planner_result.error,
    )


def ground_recommendation(
    planner_result: PlannerResult,
    explanation: str,
    conflicting: Optional[Dict[str, Any]] = None,
) -> AgentRecommendation:
    """Discard any Gemini/ADK fields that conflict with PlannerResult."""
    grounded = recommendation_from_planner(planner_result, explanation)
    if not conflicting:
        return grounded

    rec = grounded.recommended_route
    if rec is None:
        return grounded

    conflict_notes = []
    mapping = {
        "estimated_time": rec.travel_time_minutes,
        "estimated_cost": rec.cost,
        "walking_time": rec.walking_minutes,
        "transfers": rec.transfers,
        "reliability": rec.reliability_score,
        "traffic": rec.congestion_score,
        "reason_codes": grounded.reason_codes,
        "data_sources": grounded.data_sources,
        "historical_signal_used": grounded.historical_signal_used,
    }
    rec_id = conflicting.get("recommended_route_id") or conflicting.get("route_id")
    if rec_id and rec_id != rec.route_id:
        conflict_notes.append("discarded conflicting recommended_route from Gemini")
    for key, authoritative in mapping.items():
        if key in conflicting and conflicting[key] != authoritative:
            conflict_notes.append(f"discarded conflicting {key} from Gemini")

    if conflict_notes:
        grounded.warnings = list(grounded.warnings) + conflict_notes
    return grounded
