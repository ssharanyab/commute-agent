"""
Google ADK Planner Agent for commute reasoning.

Creates one ADK agent that can call existing tools. Route ranking always
comes from the deterministic planner / evaluation engine — never from Gemini.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.agent.config import (
    FALLBACK_NOTICE,
    adk_importable,
    gemini_credentials_available,
    get_gemini_api_key,
    get_gemini_model,
)
from src.agent.prompts import EXPLANATION_INSTRUCTION, SYSTEM_INSTRUCTION
from src.agent.schemas import (
    AgentCommuteRequest,
    AgentRunResult,
    ground_recommendation,
)
from src.agent import tools as agent_tools
from src.decision_engine.models import UserPreferences
from src.planner.models import CommuteRequest, PlannerResult
from src.planner.service import plan_commute as _plan_commute


MODE_DETERMINISTIC_FALLBACK = "deterministic_fallback"
MODE_ADK_GEMINI = "adk_gemini"
APP_NAME = "patchamomma_commute_agent"
AGENT_NAME = "commute_planner_agent"


def build_adk_agent(model: Optional[str] = None):
    """
    Construct the single Google ADK Planner Agent.

    Requires google-adk. Callers must check adk_importable() / credentials
    before invoking the agent against a live model.
    """
    from google.adk.agents import Agent

    return Agent(
        name=AGENT_NAME,
        model=model or get_gemini_model(),
        instruction=SYSTEM_INSTRUCTION,
        description=(
            "Understands commute intent, calls mobility/planning tools, "
            "and explains the deterministic route recommendation."
        ),
        tools=agent_tools.adk_tool_functions(),
    )


def parse_intent_from_text(text: str) -> Dict[str, Any]:
    """
    Deterministic NL → structured intent parser (no LLM).

    Used for fallback and as the structured request basis when Gemini is
    unavailable. Does not invent places or mobility facts.
    """
    raw = (text or "").strip()
    intent: Dict[str, Any] = {
        "origin": None,
        "destination": None,
        "departure_time": None,
        "arrival_deadline": None,
        "objective": None,
        "avoid_heavy_traffic": False,
        "max_walking_minutes": None,
        "max_cost": None,
        "preferred_modes": None,
        "excluded_modes": None,
        "origin_zone": None,
        "destination_zone": None,
        "modes": None,
    }
    if not raw:
        return intent

    lower = raw.lower()

    from_to = re.search(
        r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+at\b|\s+by\b|[.,;!]|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if from_to:
        intent["origin"] = from_to.group(1).strip(" .")
        intent["destination"] = from_to.group(2).strip(" .")

    time_match = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        raw,
        flags=re.IGNORECASE,
    )
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        # Fixed demo date — parser does not invent a calendar day from context.
        intent["departure_time"] = (
            f"2024-09-06T{hour:02d}:{minute:02d}:00Z"
        )

    if "avoid heavy traffic" in lower or "avoid traffic" in lower:
        intent["avoid_heavy_traffic"] = True

    walk_match = re.search(
        r"(?:walking|walk)\s+(?:under|below|less than|<)\s+(\d+(?:\.\d+)?)",
        lower,
    )
    if walk_match:
        intent["max_walking_minutes"] = float(walk_match.group(1))

    cost_match = re.search(
        r"(?:max(?:imum)?\s+cost|under|below|less than)\s*(?:inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)",
        lower,
    )
    if cost_match and "walk" not in lower[max(0, cost_match.start() - 12):cost_match.start()]:
        intent["max_cost"] = float(cost_match.group(1))

    if "fastest" in lower or "best way" in lower or "quickest" in lower:
        intent["objective"] = "time-sensitive"
    elif "cheapest" in lower or "low cost" in lower:
        intent["objective"] = "cost-sensitive"

    # Deterministic hard mode exclusions (never delegated to Gemini).
    cab_exclusion = re.search(
        r"\b(?:no|avoid|without|don'?t\s+(?:use|take)|do\s+not\s+(?:use|take))\s+"
        r"(?:cabs?|taxis?|rideshares?)\b"
        r"|"
        r"\b(?:cabs?|taxis?)\b.{0,24}\b(?:no|avoid|don'?t|do\s+not)\b",
        lower,
    )
    if cab_exclusion or "no cab" in lower or "avoid cab" in lower or "no taxi" in lower:
        intent["excluded_modes"] = ["cab"]

    zone_pair = re.search(
        r"origin[_\s-]?zone\s*[:=]?\s*(\d+).*?destination[_\s-]?zone\s*[:=]?\s*(\d+)",
        lower,
        flags=re.DOTALL,
    )
    if zone_pair:
        intent["origin_zone"] = int(zone_pair.group(1))
        intent["destination_zone"] = int(zone_pair.group(2))
    else:
        oz = re.search(r"\borigin[_\s-]?zone\s*[:=]?\s*(\d+)\b", lower)
        dz = re.search(r"\bdestination[_\s-]?zone\s*[:=]?\s*(\d+)\b", lower)
        if oz:
            intent["origin_zone"] = int(oz.group(1))
        if dz:
            intent["destination_zone"] = int(dz.group(1))

    return intent


def intent_to_agent_request(
    intent: Dict[str, Any],
    *,
    user_id: str,
    raw_text: Optional[str] = None,
) -> AgentCommuteRequest:
    """Map parsed intent dict → AgentCommuteRequest."""
    prefs = UserPreferences(
        avoid_heavy_traffic=bool(intent.get("avoid_heavy_traffic")),
        max_walking_minutes=intent.get("max_walking_minutes"),
        max_cost=intent.get("max_cost"),
        preferred_modes=intent.get("preferred_modes"),
        excluded_modes=intent.get("excluded_modes"),
    )
    if intent.get("objective") == "time-sensitive":
        prefs.time_weight = 8.0
        prefs.cost_weight = 1.0
    elif intent.get("objective") == "cost-sensitive":
        prefs.time_weight = 1.0
        prefs.cost_weight = 8.0
    if prefs.avoid_heavy_traffic:
        prefs.congestion_weight = max(prefs.congestion_weight, 5.0)

    origin = intent.get("origin") or ""
    destination = intent.get("destination") or ""
    return AgentCommuteRequest(
        user_id=user_id,
        origin=origin,
        destination=destination,
        departure_time=intent.get("departure_time"),
        arrival_deadline=intent.get("arrival_deadline"),
        objective=intent.get("objective"),
        preferences=prefs,
        origin_zone=intent.get("origin_zone"),
        destination_zone=intent.get("destination_zone"),
        modes=intent.get("modes"),
        raw_text=raw_text,
    )


def _ensure_genai_env() -> None:
    """Point google-genai / ADK at our key env without printing secrets."""
    key = get_gemini_api_key()
    if not key:
        return
    # Prefer GOOGLE_API_KEY for google-genai if unset.
    if not os.environ.get("GOOGLE_API_KEY", "").strip():
        os.environ["GOOGLE_API_KEY"] = key
    if not os.environ.get("GOOGLE_GENAI_API_KEY", "").strip():
        os.environ["GOOGLE_GENAI_API_KEY"] = key


def _extract_text_from_adk_events(events: List[Any]) -> str:
    chunks: List[str] = []
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _invoke_adk_explanation(
    user_text: str,
    planner_result: PlannerResult,
    *,
    user_id: str,
) -> Tuple[str, bool, str]:
    """
    Run the ADK agent to produce a grounded explanation.

    Returns (explanation, success, error_detail).
    success is True only when usable Gemini text was produced.
    Failures never report success — including empty event streams from
    Runner.run swallowing background-thread exceptions.
    """
    if not adk_importable() or not gemini_credentials_available():
        return "", False, "ADK/Gemini unavailable"

    _ensure_genai_env()

    import asyncio

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = build_adk_agent()
    session_service = InMemorySessionService()
    session_id = f"session-{uuid.uuid4().hex[:12]}"
    session_service.create_session_sync(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    payload = {
        "user_request": user_text,
        "planner_result": planner_result.to_dict(),
        "instructions": EXPLANATION_INSTRUCTION,
    }
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    "Explain this deterministic commute plan for the user. "
                    "Do not change the recommended route or any metrics.\n\n"
                    + json.dumps(payload, default=str)
                )
            )
        ],
    )

    async def _collect_events():
        out = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            out.append(event)
        return out

    try:
        events = asyncio.run(_collect_events())
    except Exception as exc:
        # Never include env/credential values in the message.
        detail = f"{type(exc).__name__}: {str(exc)[:240]}"
        return "", False, f"ADK execution failed: {detail}"

    if not events:
        return "", False, "ADK execution failed: no events returned"

    text = _extract_text_from_adk_events(events)
    if not text:
        return "", False, "ADK execution failed: no text response from model"

    return text, True, ""


def _probe_context_tools(
    agent_request: AgentCommuteRequest,
) -> Tuple[List[str], List[str]]:
    """Call unavailable context tools so their status is explicit."""
    selected = ["plan_commute"]
    warnings: List[str] = []

    prefs = agent_tools.get_user_preferences(agent_request.user_id)
    selected.append("get_user_preferences")
    if not prefs.get("available", True):
        warnings.append("user_preferences unavailable (not_configured)")

    weather = agent_tools.get_weather(agent_request.origin or "unknown")
    selected.append("get_weather")
    if not weather.get("available", True):
        warnings.append("weather unavailable (not_configured)")

    disruptions = agent_tools.get_disruptions(
        agent_request.origin or "",
        agent_request.destination or "",
    )
    selected.append("get_disruptions")
    if not disruptions.get("available", True):
        warnings.append("disruptions unavailable (not_configured)")

    history = agent_tools.get_commute_history(agent_request.user_id)
    selected.append("get_commute_history")
    if not history.get("available", True):
        warnings.append("commute_history unavailable (not_configured)")

    return selected, warnings


def run_commute_agent(
    user_text: str,
    *,
    user_id: str = "demo-user",
    intent_override: Optional[Dict[str, Any]] = None,
    conflicting_llm_fields: Optional[Dict[str, Any]] = None,
    invoke_gemini: bool = True,
    api_key: Optional[str] = None,
) -> AgentRunResult:
    """
    End-to-end agent entrypoint.

    Always runs the deterministic planner for ranking. Gemini/ADK is used
    only for explanation when credentials are available and invoke_gemini
    is True. Missing credentials → deterministic_fallback (never faked).
    """
    parsed = intent_override if intent_override is not None else parse_intent_from_text(user_text)
    agent_request = intent_to_agent_request(
        parsed, user_id=user_id, raw_text=user_text
    )
    commute_request: CommuteRequest = agent_request.to_commute_request()

    planner_result = _plan_commute(commute_request, api_key=api_key)
    tools_selected, context_warnings = _probe_context_tools(agent_request)

    gemini_available = gemini_credentials_available()
    gemini_invoked = False
    adk_invoked = False
    mode = MODE_DETERMINISTIC_FALLBACK
    explanation = FALLBACK_NOTICE

    if invoke_gemini and gemini_available and adk_importable():
        try:
            text, success, error_detail = _invoke_adk_explanation(
                user_text, planner_result, user_id=user_id
            )
            if success and text:
                adk_invoked = True
                gemini_invoked = True
                mode = MODE_ADK_GEMINI
                explanation = text
            else:
                explanation = FALLBACK_NOTICE
                mode = MODE_DETERMINISTIC_FALLBACK
                adk_invoked = False
                gemini_invoked = False
                warn = error_detail or "ADK execution failed: empty response"
                context_warnings = list(context_warnings) + [warn]
        except Exception as exc:
            explanation = FALLBACK_NOTICE
            mode = MODE_DETERMINISTIC_FALLBACK
            gemini_invoked = False
            adk_invoked = False
            context_warnings = list(context_warnings) + [
                f"gemini/adk invocation failed: {type(exc).__name__}"
            ]

    recommendation = ground_recommendation(
        planner_result,
        explanation,
        conflicting=conflicting_llm_fields,
    )
    if context_warnings:
        recommendation.warnings = list(recommendation.warnings) + list(context_warnings)

    return AgentRunResult(
        recommendation=recommendation,
        parsed_intent=dict(parsed),
        commute_request=commute_request,
        planner_result=planner_result,
        tools_selected=tools_selected,
        gemini_available=gemini_available,
        gemini_invoked=gemini_invoked,
        adk_invoked=adk_invoked,
        mode=mode,
    )
