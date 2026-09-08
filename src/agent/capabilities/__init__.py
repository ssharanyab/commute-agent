"""
Structured capability contracts for ADK Mobility Orchestration (Phase 5D).

Reuse Journey Builder / Decision Engine models where possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class CapabilityInvocation:
    name: str
    status: str  # invoked | skipped | failed | unavailable
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


@dataclass
class MobilityContext:
    network_snapshot_versions: Dict[str, str]
    relevant_stops: List[Dict[str, Any]]
    relevant_stations: List[Dict[str, Any]]
    relevant_routes: List[Dict[str, Any]]
    provenance: Dict[str, Any]
    available: bool = True
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "network_snapshot_versions": dict(self.network_snapshot_versions),
            "relevant_stops": list(self.relevant_stops),
            "relevant_stations": list(self.relevant_stations),
            "relevant_routes": list(self.relevant_routes),
            "provenance": dict(self.provenance),
            "available": self.available,
            "warnings": list(self.warnings),
        }


@dataclass
class TrafficEnrichmentResult:
    journey_id: str
    leg_index: int
    available: bool
    duration_minutes: Optional[float] = None
    distance_meters: Optional[float] = None
    traffic_info: Dict[str, Any] = field(default_factory=dict)
    polyline: Optional[str] = None
    route_token: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "journey_id": self.journey_id,
            "leg_index": self.leg_index,
            "available": self.available,
            "duration_minutes": self.duration_minutes,
            "distance_meters": self.distance_meters,
            "traffic_info": dict(self.traffic_info),
            "polyline": self.polyline,
            "route_token": self.route_token,
            "provenance": dict(self.provenance),
            "reason": self.reason,
        }


@dataclass
class HistoricalCapabilityResult:
    available: bool
    coverage: bool
    journey_ref: Optional[str]
    expected_duration_minutes: Optional[float]
    reliability: Optional[float]
    deviation: Optional[Any]
    confidence: Optional[float]
    provenance: Dict[str, Any]
    signal: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "coverage": self.coverage,
            "journey_ref": self.journey_ref,
            "expected_duration_minutes": self.expected_duration_minutes,
            "reliability": self.reliability,
            "deviation": self.deviation,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
            "signal": dict(self.signal),
            "reason": self.reason,
        }


@dataclass
class ContextCapabilityResult:
    available: bool
    weather: Optional[Dict[str, Any]]
    timestamp: Optional[str]
    provenance: Dict[str, Any]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "weather": self.weather,
            "timestamp": self.timestamp,
            "provenance": dict(self.provenance),
            "reason": self.reason,
        }


@dataclass
class PersonalizationResult:
    excluded_modes: Optional[List[str]]
    max_walking_minutes: Optional[float]
    max_transfers: Optional[int]
    preference_profile: Optional[str]
    preferences: Dict[str, Any]
    source: str  # request | stored | default
    stored_profile_available: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "excluded_modes": list(self.excluded_modes)
            if self.excluded_modes
            else None,
            "max_walking_minutes": self.max_walking_minutes,
            "max_transfers": self.max_transfers,
            "preference_profile": self.preference_profile,
            "preferences": dict(self.preferences),
            "source": self.source,
            "stored_profile_available": self.stored_profile_available,
        }


@dataclass
class DecisionCapabilityResult:
    ranked_route_ids: List[str]
    recommended_route_id: Optional[str]
    category_assignments: Dict[str, str]
    scores: Dict[str, float]
    reason_codes: List[str]
    evaluation: Dict[str, Any]
    authoritative: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ranked_route_ids": list(self.ranked_route_ids),
            "recommended_route_id": self.recommended_route_id,
            "category_assignments": dict(self.category_assignments),
            "scores": dict(self.scores),
            "reason_codes": list(self.reason_codes),
            "evaluation": dict(self.evaluation),
            "authoritative": self.authoritative,
        }


@dataclass
class OrchestrationMetadata:
    capabilities: List[CapabilityInvocation] = field(default_factory=list)
    network_snapshot_versions: Dict[str, str] = field(default_factory=dict)
    journey_candidate_count: int = 0
    enrichment_count: int = 0
    decision_engine_invoked: bool = False
    gemini_available: bool = False
    gemini_invoked: bool = False
    explanation_mode: str = "deterministic_fallback"
    fallbacks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def record(
        self,
        name: str,
        status: str,
        reason: str,
        **detail: Any,
    ) -> None:
        self.capabilities.append(
            CapabilityInvocation(
                name=name, status=status, reason=reason, detail=detail
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capabilities": [c.to_dict() for c in self.capabilities],
            "network_snapshot_versions": dict(self.network_snapshot_versions),
            "journey_candidate_count": self.journey_candidate_count,
            "enrichment_count": self.enrichment_count,
            "decision_engine_invoked": self.decision_engine_invoked,
            "gemini_available": self.gemini_available,
            "gemini_invoked": self.gemini_invoked,
            "explanation_mode": self.explanation_mode,
            "fallbacks": list(self.fallbacks),
            "warnings": list(self.warnings),
        }
