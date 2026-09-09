"""
ADK + Gemini reasoning layer for the commute agent.

Deterministic Journey Builder / Decision Engine remain authoritative for
candidate discovery and ranking. Gemini explains only.

Imports are lazy to avoid circular import with decision_engine ↔ planner.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentCommuteRequest",
    "AgentRecommendation",
    "AgentRunResult",
    "recommendation_from_planner",
    "ground_recommendation",
    "build_adk_agent",
    "parse_intent_from_text",
    "run_commute_agent",
    "run_adaptive_replan",
    "MobilityOrchestrator",
    "OrchestratorRequest",
    "OrchestrationResult",
    "plan_commute_with_adk",
    "CANONICAL_DEMO_DEPARTURE",
    "CANONICAL_DEMO_OD",
    "ELECTRONIC_CITY",
    "MAJESTIC",
    "AdaptiveReplanRequest",
    "PlanSnapshot",
    "run_adaptive_replan_from_snapshot",
    "snapshot_from_orchestration",
    "snapshot_from_planner_result",
    "ReplanDecision",
    "ContextChangeType",
]


def __getattr__(name: str) -> Any:
    if name in {
        "AgentCommuteRequest",
        "AgentRecommendation",
        "AgentRunResult",
        "recommendation_from_planner",
        "ground_recommendation",
    }:
        from src.agent import schemas as _schemas

        return getattr(_schemas, name)
    if name in {
        "build_adk_agent",
        "parse_intent_from_text",
        "run_commute_agent",
    }:
        from src.agent import planner as _planner

        return getattr(_planner, name)
    if name == "run_adaptive_replan":
        from src.agent.replan import run_adaptive_replan

        return run_adaptive_replan
    if name in {
        "MobilityOrchestrator",
        "OrchestratorRequest",
        "OrchestrationResult",
        "plan_commute_with_adk",
    }:
        from src.agent import orchestrator as _orch

        return getattr(_orch, name)
    if name in {
        "CANONICAL_DEMO_DEPARTURE",
        "CANONICAL_DEMO_OD",
        "ELECTRONIC_CITY",
        "MAJESTIC",
    }:
        from src.agent import demo_od as _demo

        return getattr(_demo, name)
    if name in {
        "AdaptiveReplanRequest",
        "PlanSnapshot",
        "run_adaptive_replan_from_snapshot",
        "snapshot_from_orchestration",
        "snapshot_from_planner_result",
    }:
        from src.agent import adaptive as _adaptive

        return getattr(_adaptive, name)
    if name in {"ReplanDecision", "ContextChangeType"}:
        from src.planner import models as _pm

        return getattr(_pm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
