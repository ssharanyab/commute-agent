"""
ADK/Gemini explanation wrapper for adaptive replanning.

Deterministic replan_commute() remains the decision authority.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional, Tuple

from src.agent.config import (
    FALLBACK_NOTICE,
    adk_importable,
    gemini_credentials_available,
    get_gemini_model,
)
from src.agent.planner import (
    APP_NAME,
    MODE_ADK_GEMINI,
    MODE_DETERMINISTIC_FALLBACK,
    _ensure_genai_env,
    _extract_text_from_adk_events,
    build_adk_agent,
)
from src.agent.prompts import REPLAN_EXPLANATION_INSTRUCTION, SYSTEM_INSTRUCTION
from src.planner.models import ContextChange, ReplanResult, CommuteRequest, PlannerResult
from src.planner.replan import replan_commute


def _invoke_replan_explanation(
    replan_result: ReplanResult,
    *,
    user_id: str,
) -> Tuple[str, bool, str]:
    """Ask Gemini to explain before/after deterministic replan. Never picks routes."""
    if not adk_importable() or not gemini_credentials_available():
        return "", False, "ADK/Gemini unavailable"

    _ensure_genai_env()

    import asyncio

    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    # Single explanation agent — no tools needed to invent mobility facts.
    agent = Agent(
        name="commute_replan_explainer",
        model=get_gemini_model(),
        instruction=SYSTEM_INSTRUCTION + "\n\n" + REPLAN_EXPLANATION_INSTRUCTION,
        description="Explains deterministic replan outcomes without changing recommendations.",
        tools=[],
    )
    session_service = InMemorySessionService()
    session_id = f"replan-{uuid.uuid4().hex[:12]}"
    session_service.create_session_sync(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    payload = {
        "instructions": REPLAN_EXPLANATION_INSTRUCTION,
        "context_change": replan_result.context_change.to_dict(),
        "previous_route_id": replan_result.previous_route_id,
        "new_route_id": replan_result.new_route_id,
        "recommendation_changed": replan_result.recommendation_changed,
        "provenance_notes": replan_result.provenance_notes,
        "initial_evaluation": (
            replan_result.initial.evaluation.to_dict()
            if replan_result.initial.evaluation
            else None
        ),
        "updated_evaluation": (
            replan_result.updated.evaluation.to_dict()
            if replan_result.updated.evaluation
            else None
        ),
    }
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    "Explain this deterministic replan. Do not change the recommended route.\n\n"
                    + json.dumps(payload, default=str)
                )
            )
        ],
    )

    async def _collect():
        out = []
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            out.append(event)
        return out

    try:
        events = asyncio.run(_collect())
    except Exception as exc:
        return "", False, f"ADK execution failed: {type(exc).__name__}: {str(exc)[:240]}"

    if not events:
        return "", False, "ADK execution failed: no events returned"
    text = _extract_text_from_adk_events(events)
    if not text:
        return "", False, "ADK execution failed: no text response from model"
    return text, True, ""


def run_adaptive_replan(
    initial_request: CommuteRequest,
    initial_result: PlannerResult,
    context_change: ContextChange,
    *,
    user_id: str = "demo-user",
    invoke_gemini: bool = True,
    api_key: Optional[str] = None,
    refresh_live_routes: bool = False,
) -> ReplanResult:
    """
    Deterministic replan + optional Gemini explanation of the change.
    """
    result = replan_commute(
        initial_request,
        initial_result,
        context_change,
        api_key=api_key,
        refresh_live_routes=refresh_live_routes,
    )

    result.gemini_available = gemini_credentials_available()
    result.gemini_invoked = False
    result.adk_invoked = False
    result.mode = MODE_DETERMINISTIC_FALLBACK
    result.explanation = FALLBACK_NOTICE

    if not invoke_gemini or not result.gemini_available or not adk_importable():
        return result

    text, success, err = _invoke_replan_explanation(result, user_id=user_id)
    if success and text:
        result.explanation = text
        result.gemini_invoked = True
        result.adk_invoked = True
        result.mode = MODE_ADK_GEMINI
    else:
        result.explanation = FALLBACK_NOTICE
        result.gemini_invoked = False
        result.adk_invoked = False
        result.mode = MODE_DETERMINISTIC_FALLBACK
        if err:
            result.updated.warnings = list(result.updated.warnings) + [err]
    return result
