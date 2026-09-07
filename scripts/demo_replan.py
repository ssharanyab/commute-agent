"""
Demo: adaptive replanning (initial → context change → replan → Gemini explain).

Uses live Maps when GOOGLE_MAPS_API_KEY is set; otherwise fixture Maps data.
Context change is SIMULATED so the demo reliably shows a recommendation change.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.decision_engine.models import UserPreferences
from src.mobility.models import TravelMode
from src.mobility.service import _clear_cache, get_candidate_routes
from src.planner.models import CommuteRequest, ContextChange
from src.planner.service import plan_commute
from src.agent.replan import run_adaptive_replan
from src.agent.config import FALLBACK_NOTICE
from src.mobility.route_adapter import field_provenance
from tests.maps_fixtures import (
    get_drive_alternative_routes_fixture,
    get_transit_route_fixture,
)


ORIGIN = "Electronic City, Bengaluru"
DESTINATION = "Koramangala, Bengaluru"


def _banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def _is_live_maps() -> bool:
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return bool(key and key not in {"", "your_key_here", "changeme"})


def _print_plan(label: str, result) -> None:
    ev = result.evaluation
    rec = ev.recommended_route if ev else None
    print(f"\n[{label}]")
    if result.error:
        print(f"  error: {result.error} ({result.error_detail})")
        return
    if rec:
        print(f"  recommended: {rec.route_id} | mode={rec.mode} | {rec.travel_time_minutes} min | INR {rec.cost}")
        print(f"  score: {ev.score:.2f}")
        print(f"  reasons: {', '.join(ev.reason_codes) if ev.reason_codes else '-'}")
        print(f"  congestion: {rec.congestion_score:.2f}")
    print(f"  data_sources: {result.data_sources}")
    print("  ranked:")
    for i, sr in enumerate(ev.ranked_routes[:5], 1):
        flag = "OK" if sr.is_valid else "INVALID"
        print(
            f"    {i}. [{flag}] {sr.route.route_id:<18} "
            f"score={sr.final_score:>7.2f} time={sr.route.travel_time_minutes} "
            f"cong={sr.route.congestion_score:.2f}"
        )


def _fixture_post(*args, **kwargs):
    body = kwargs.get("json", {})
    mode = body.get("travelMode", "DRIVE")
    mock = MagicMock()
    mock.status_code = 200
    if mode == "DRIVE":
        mock.json.return_value = get_drive_alternative_routes_fixture()
    else:
        mock.json.return_value = get_transit_route_fixture()
    return mock


def run_demo() -> None:
    _clear_cache()
    _banner("ADAPTIVE REPLANNING DEMO")
    departure = (datetime.now(timezone.utc) + timedelta(minutes=45)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    prefs = UserPreferences(
        time_weight=8.0,
        cost_weight=1.0,
        walking_weight=2.0,
        congestion_weight=5.0,
        reliability_weight=2.0,
        avoid_heavy_traffic=True,
        max_walking_minutes=12.0,
    )
    request = CommuteRequest(
        user_id="demo-user",
        origin=ORIGIN,
        destination=DESTINATION,
        departure_time=departure,
        objective="avoid-traffic",
        preferences=prefs,
        modes=[TravelMode.DRIVE, TravelMode.TRANSIT],
    )

    live = _is_live_maps()
    if live:
        print("  Maps mode: LIVE Google Maps Routes API")
        initial = plan_commute(request)
        maps_label = "live"
    else:
        print("  Maps mode: FIXTURE (not live Maps)")
        print("  Set GOOGLE_MAPS_API_KEY for live candidates.")
        with patch("requests.post", side_effect=_fixture_post):
            initial = plan_commute(request, api_key="MOCK_KEY_FOR_DEMO")
        maps_label = "fixture→adapted (live fields from fixture schema; costs/heuristics heuristic)"

    _banner("1. INITIAL PLAN")
    _print_plan("INITIAL", initial)
    if not initial.evaluation or not initial.evaluation.recommended_route:
        print("\n  [ABORT] No initial recommendation.")
        return

    before_id = initial.evaluation.recommended_route.route_id
    prov = field_provenance(TravelMode.DRIVE)
    print("\n  Provenance (DRIVE adapter policy):")
    print(f"    travel_time_minutes: {prov['travel_time_minutes']}")
    print(f"    cost: {prov['cost']}")
    print(f"    congestion_score: {prov['congestion_score']}")
    print(f"    maps_candidate_source: {maps_label}")

    change = ContextChange(
        traffic_changed=True,
        context_source="simulated",
        target_route_id=before_id,
        congestion_delta=0.55,
        travel_time_delta_minutes=22.0,
        description=(
            f"SIMULATED demo traffic spike on {before_id}: "
            "+0.55 congestion, +22 minutes"
        ),
    )

    _banner("2. CONTEXT CHANGE")
    print(f"  context_source: {change.context_source}  ← not live Maps")
    print(f"  traffic_changed: {change.traffic_changed}")
    print(f"  target_route_id: {change.target_route_id}")
    print(f"  congestion_delta: {change.congestion_delta}")
    print(f"  travel_time_delta_minutes: {change.travel_time_delta_minutes}")
    print(f"  description: {change.description}")

    _banner("3. REPLANNED PLAN")
    result = run_adaptive_replan(
        request,
        initial,
        change,
        user_id="demo-user",
        invoke_gemini=True,
    )
    _print_plan("REPLAN", result.updated)
    print(f"\n  recommendation_changed: {result.recommendation_changed}")
    print(f"  previous_route_id: {result.previous_route_id}")
    print(f"  new_route_id:      {result.new_route_id}")
    print(f"  provenance_notes:  {result.provenance_notes}")

    _banner("4. GEMINI EXPLANATION OF CHANGE")
    print(f"  gemini_available: {result.gemini_available}")
    print(f"  gemini_invoked:   {result.gemini_invoked}")
    print(f"  adk_invoked:      {result.adk_invoked}")
    print(f"  mode:             {result.mode}")
    if result.gemini_invoked:
        print("  [GEMINI]")
        print(f"  {result.explanation}")
    else:
        print(f"  {FALLBACK_NOTICE}")
        if result.explanation == FALLBACK_NOTICE:
            print("  (Deterministic replan still applied; no fabricated LLM text.)")

    _banner("5. VALUE CLASSES")
    print(f"  Maps candidates:     {maps_label}")
    print("  Adapter estimates:   heuristic (cost/reliability/etc. per provenance)")
    print("  Context overlay:     SIMULATED (explicit demo traffic spike)")
    print("  Route ranking:       deterministic evaluator (authoritative)")
    print()


if __name__ == "__main__":
    run_demo()
