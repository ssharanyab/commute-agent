"""
Phase 5E adaptive replanning helpers for ADK orchestration.

Builds in-memory plan snapshots from OrchestrationResult / PlannerResult
and runs deterministic replan_commute.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agent.config import FALLBACK_NOTICE
from src.decision_engine.models import EvaluationResult, RouteCandidate, UserPreferences
from src.journey_builder.models import Journey
from src.planner.models import (
    CommuteRequest,
    ContextChange,
    PlannerResult,
    ReplanDecision,
    ReplanResult,
)
from src.planner.replan import replan_commute


@dataclass
class PlanSnapshot:
    """In-memory baseline for adaptive replanning (persistable later)."""

    plan_id: str
    timestamp: datetime
    request: CommuteRequest
    selected_journey_id: Optional[str]
    candidate_ids: List[str]
    routes: List[RouteCandidate]
    scores: Dict[str, float]
    evaluation: Optional[EvaluationResult]
    planner_result: PlannerResult
    journeys: List[Journey] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    data_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "timestamp": self.timestamp.isoformat(),
            "request": self.request.to_dict(),
            "selected_journey_id": self.selected_journey_id,
            "candidate_ids": list(self.candidate_ids),
            "routes": [r.to_dict() for r in self.routes],
            "scores": dict(self.scores),
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "journeys": [j.to_dict() for j in self.journeys],
            "context_snapshot": dict(self.context_snapshot),
            "data_sources": list(self.data_sources),
        }


@dataclass
class AdaptiveReplanRequest:
    original_request: CommuteRequest
    previous_plan: PlanSnapshot
    context_changes: List[ContextChange]
    current_timestamp: Optional[datetime] = None
    invoke_gemini: bool = False


def snapshot_from_planner_result(
    result: PlannerResult,
    *,
    plan_id: Optional[str] = None,
    journeys: Optional[List[Journey]] = None,
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> PlanSnapshot:
    evaluation = result.evaluation
    selected = (
        evaluation.recommended_route.route_id
        if evaluation and evaluation.recommended_route
        else None
    )
    scores = {
        s.route.route_id: float(s.final_score)
        for s in (evaluation.ranked_routes if evaluation else [])
        if s.is_valid
    }
    return PlanSnapshot(
        plan_id=plan_id or f"plan-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc),
        request=result.request,
        selected_journey_id=selected,
        candidate_ids=[r.route_id for r in result.routes],
        routes=list(result.routes),
        scores=scores,
        evaluation=evaluation,
        planner_result=result,
        journeys=list(journeys or []),
        context_snapshot=dict(context_snapshot or {}),
        data_sources=list(result.data_sources or []),
    )


def snapshot_from_orchestration(orch_result: Any) -> PlanSnapshot:
    """Build snapshot from Phase 5D OrchestrationResult."""
    if orch_result.legacy_planner_result is not None:
        base = orch_result.legacy_planner_result
    else:
        req = CommuteRequest(
            user_id="orchestrator",
            origin="snapshot",
            destination="snapshot",
            preferences=None,
        )
        if hasattr(orch_result, "recommendation") and orch_result.evaluation:
            # Reconstruct minimal PlannerResult
            from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC

            req = CommuteRequest(
                user_id="orchestrator",
                origin=ELECTRONIC_CITY.address,
                destination=MAJESTIC.address,
            )
        base = PlannerResult(
            request=req,
            routes=list(orch_result.route_candidates),
            evaluation=orch_result.evaluation,
            data_sources=["journey_builder", "decision_engine"],
            historical_signal_used=bool(
                orch_result.historical and orch_result.historical.coverage
            ),
            warnings=list(orch_result.metadata.warnings),
        )
    return snapshot_from_planner_result(
        base,
        journeys=list(getattr(orch_result, "journeys", []) or []),
        context_snapshot={
            "metadata": orch_result.metadata.to_dict()
            if hasattr(orch_result.metadata, "to_dict")
            else {},
            "network_snapshot_versions": dict(
                orch_result.metadata.network_snapshot_versions
            )
            if hasattr(orch_result.metadata, "network_snapshot_versions")
            else {},
        },
    )


def merge_context_changes(changes: List[ContextChange]) -> ContextChange:
    """Merge multiple structured changes into one ContextChange for replan_commute."""
    if not changes:
        return ContextChange(context_source="none", change_type="NONE")
    if len(changes) == 1:
        return changes[0]

    primary = changes[0]
    invalidate: List[str] = []
    excluded: List[str] = []
    traffic = False
    disruption = False
    weather = False
    source = primary.context_source
    target = primary.target_route_id
    cong = primary.congestion_delta
    tdelta = primary.travel_time_delta_minutes
    abs_t = primary.absolute_travel_time_minutes
    desc_parts = []
    for c in changes:
        traffic = traffic or c.traffic_changed
        disruption = disruption or c.disruption_changed
        weather = weather or c.weather_changed
        if c.context_source == "simulated":
            source = "simulated"
        elif c.context_source == "live" and source != "simulated":
            source = "live"
        if c.target_route_id:
            target = c.target_route_id
        cong += c.congestion_delta
        tdelta += c.travel_time_delta_minutes
        if c.absolute_travel_time_minutes is not None:
            abs_t = c.absolute_travel_time_minutes
        if c.invalidate_route_ids:
            invalidate.extend(c.invalidate_route_ids)
        if c.excluded_modes_update:
            excluded.extend(c.excluded_modes_update)
        if c.description:
            desc_parts.append(c.description)

    return ContextChange(
        traffic_changed=traffic,
        disruption_changed=disruption,
        weather_changed=weather,
        context_source=source,
        target_route_id=target,
        congestion_delta=cong,
        travel_time_delta_minutes=tdelta,
        absolute_travel_time_minutes=abs_t,
        invalidate_route_ids=invalidate or None,
        excluded_modes_update=excluded or None,
        description="; ".join(desc_parts),
        change_type=primary.inferred_change_type(),
        requires_reevaluation=any(c.requires_reevaluation for c in changes),
    )


def run_adaptive_replan_from_snapshot(
    request: AdaptiveReplanRequest,
    *,
    api_key: Optional[str] = None,
) -> ReplanResult:
    """
    ADK-facing adaptive replan entry: snapshot + structured changes → ReplanResult.
    """
    merged = merge_context_changes(list(request.context_changes))
    result = replan_commute(
        request.original_request,
        request.previous_plan.planner_result,
        merged,
        api_key=api_key,
        original_plan_id=request.previous_plan.plan_id,
    )
    result.orchestration_metadata = {
        **dict(result.orchestration_metadata),
        "adaptive_from_snapshot": True,
        "plan_id": request.previous_plan.plan_id,
        "context_change_count": len(request.context_changes),
        "timestamp": (
            request.current_timestamp or datetime.now(timezone.utc)
        ).isoformat(),
    }
    if not result.explanation:
        result.explanation = _deterministic_replan_explanation(result)
    return result


def _deterministic_replan_explanation(result: ReplanResult) -> str:
    decision = result.decision or "UNKNOWN"
    parts = [
        f"Adaptive replan decision: {decision}.",
        f"Previous journey: {result.previous_route_id}.",
        f"New journey: {result.new_route_id}.",
    ]
    if result.decision_factors:
        parts.append("Factors: " + "; ".join(result.decision_factors[:5]))
    if result.context_change.context_source == "simulated":
        parts.append("Context source: simulation (not live Google traffic).")
    parts.append(FALLBACK_NOTICE)
    return " ".join(parts)
