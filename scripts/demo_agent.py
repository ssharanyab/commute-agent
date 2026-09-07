"""
Demo: ADK + Gemini commute agent (with deterministic fallback).

Example: Electronic City → Koramangala at 8 AM.
Uses Maps fixtures when GOOGLE_MAPS_API_KEY is unset.
Never fabricates a Gemini response when credentials are missing.
"""

import os
from unittest.mock import MagicMock, patch

from src.agent.config import FALLBACK_NOTICE, gemini_credentials_available
from src.agent.planner import run_commute_agent
from src.mobility.service import _clear_cache
from tests.maps_fixtures import (
    get_drive_alternative_routes_fixture,
    get_transit_route_fixture,
    get_walk_route_fixture,
)

USER_TEXT = (
    "Find the best way from Electronic City to Koramangala at 8 AM. "
    "Avoid heavy traffic and keep walking under 10 minutes."
)


def _is_live_maps_key() -> bool:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return bool(api_key and api_key != "your_key_here")


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def _fixture_post(*args, **kwargs):
    body = kwargs.get("json", {})
    mode = body.get("travelMode", "DRIVE")
    mock = MagicMock()
    mock.status_code = 200
    if mode == "DRIVE":
        mock.json.return_value = get_drive_alternative_routes_fixture()
    elif mode == "TRANSIT":
        mock.json.return_value = get_transit_route_fixture()
    else:
        mock.json.return_value = get_walk_route_fixture()
    return mock


def _print_run(result) -> None:
    print_banner("1. NATURAL LANGUAGE REQUEST")
    print(f"  {USER_TEXT}")

    print_banner("2. PARSED / STRUCTURED INTENT")
    for key, value in result.parsed_intent.items():
        print(f"  {key}: {value}")

    print_banner("3. PLANNER / TOOL EXECUTION")
    print(f"  tools_selected: {result.tools_selected}")
    print(f"  mode: {result.mode}")
    print(f"  gemini_available: {result.gemini_available}")
    print(f"  gemini_invoked: {result.gemini_invoked}")
    print(f"  adk_invoked: {result.adk_invoked}")

    pr = result.planner_result
    print_banner("4. CANDIDATE ROUTES")
    if pr is None:
        print("  (none)")
    else:
        for route in pr.routes:
            print(
                f"  * [{route.route_id}] mode={route.mode:<8} "
                f"{route.travel_time_minutes} min | INR {route.cost} | "
                f"walk {route.walking_minutes} min | "
                f"congestion {route.congestion_score:.2f}"
            )

    print_banner("5. DETERMINISTIC EVALUATION")
    if pr and pr.evaluation:
        for idx, scored in enumerate(pr.evaluation.ranked_routes, 1):
            valid = "OK" if scored.is_valid else "INVALID"
            codes = ", ".join(scored.reason_codes) if scored.reason_codes else "-"
            print(
                f"  {idx}. [{valid}] {scored.route.route_id:<22} | "
                f"{scored.final_score:>7.2f} | {codes}"
            )
    else:
        print("  (no evaluation)")

    rec = result.recommendation
    print_banner("6. RECOMMENDED ROUTE")
    if rec.recommended_route:
        r = rec.recommended_route
        print(f"  route_id:     {r.route_id}")
        print(f"  mode:         {r.mode}")
        print(f"  time (min):   {rec.estimated_time}")
        print(f"  cost:         {rec.estimated_cost}")
        print(f"  walking:      {rec.walking_time}")
        print(f"  transfers:    {rec.transfers}")
        print(f"  reliability:  {rec.reliability}")
        print(f"  traffic:      {rec.traffic}")
    else:
        print("  (none)")

    print_banner("7. REASON CODES")
    print(f"  {rec.reason_codes}")

    print_banner("8. DATA SOURCES")
    print(f"  {rec.data_sources}")
    print(f"  historical_signal_used: {rec.historical_signal_used}")

    print_banner("9. GEMINI EXPLANATION / FALLBACK")
    if result.gemini_invoked and result.mode != "deterministic_fallback":
        print("  [GEMINI] Explanation from ADK/Gemini:")
        print(f"  {rec.explanation}")
    else:
        print(f"  {FALLBACK_NOTICE}")
        if rec.explanation == FALLBACK_NOTICE:
            print("  (No fabricated LLM explanation.)")
        else:
            print(f"  explanation field: {rec.explanation}")

    if rec.warnings:
        print_banner("WARNINGS")
        for w in rec.warnings:
            print(f"  - {w}")


def run_demo() -> None:
    _clear_cache()
    print_banner("PATCHAMOMMA - ADK COMMUTE AGENT DEMO")
    print(f"  Gemini credentials available: {gemini_credentials_available()}")

    if _is_live_maps_key():
        print("  [LIVE MAPS] Using real Google Maps Routes API.")
        result = run_commute_agent(USER_TEXT)
        _print_run(result)
        return

    print("  [FIXTURE MODE] GOOGLE_MAPS_API_KEY is not configured.")
    print("  Results use OFFLINE MAPS FIXTURES — not live Google Maps data.")

    with patch("requests.post", side_effect=_fixture_post):
        result = run_commute_agent(USER_TEXT, api_key="MOCK_KEY_FOR_DEMO")
        _print_run(result)


if __name__ == "__main__":
    run_demo()
