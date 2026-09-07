"""
Demo: commute planner orchestration (Maps -> optional ML -> evaluation).

Electronic City → Koramangala with two preference profiles.
If GOOGLE_MAPS_API_KEY is not configured, fixture Maps payloads are used
and the run is explicitly labeled as FIXTURE MODE — not live Maps data.
"""

import os
from unittest.mock import patch, MagicMock

from src.planner import CommuteRequest, plan_commute
from src.decision_engine.models import UserPreferences
from src.mobility.service import _clear_cache
from tests.maps_fixtures import (
    get_drive_alternative_routes_fixture,
    get_transit_route_fixture,
    get_walk_route_fixture,
)

ORIGIN = "Electronic City Phase 1, Bengaluru"
DESTINATION = "Koramangala 4th Block, Bengaluru"
DEPARTURE_TIME = "2024-09-06T08:00:00Z"


def _is_live_key() -> bool:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return bool(api_key and api_key != "your_key_here")


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_planner_result(label: str, result) -> None:
    print_banner(label)
    print("  Request:")
    print(f"    user_id:         {result.request.user_id}")
    print(f"    origin:          {result.request.origin}")
    print(f"    destination:     {result.request.destination}")
    print(f"    departure_time:  {result.request.departure_time}")
    print(f"    objective:       {result.request.objective}")
    print(f"    origin_zone:     {result.request.origin_zone}")
    print(f"    destination_zone:{result.request.destination_zone}")

    print(f"\n  Data sources: {result.data_sources}")
    print(f"  Historical ML used: {result.historical_signal_used}")
    if result.warnings:
        print(f"  Warnings: {result.warnings}")
    if result.error:
        print(f"  Error: {result.error} ({result.error_detail})")
        return

    print(f"\n  Candidate routes ({len(result.routes)}):")
    for route in result.routes:
        sig = route.historical_mobility_signal
        coverage = "YES" if (sig and sig.get("has_historical_coverage")) else "NO"
        print(
            f"    * [{route.route_id}] mode={route.mode:<8} "
            f"{route.travel_time_minutes} min | INR {route.cost} | "
            f"walk {route.walking_minutes} min | congestion {route.congestion_score:.2f} | "
            f"ML coverage={coverage}"
        )

    evaluation = result.evaluation
    if evaluation is None:
        print("\n  No evaluation produced.")
        return

    rec = evaluation.recommended_route
    if rec:
        print(
            f"\n  Recommended: [{rec.route_id}] {rec.mode} | "
            f"{rec.travel_time_minutes} min | INR {rec.cost}"
        )
        print(f"  Score: {evaluation.score:.2f}")
        print(f"  Reason codes: {', '.join(evaluation.reason_codes) if evaluation.reason_codes else '-'}")
    else:
        print("\n  Recommended: None (no valid route)")

    print("\n  Ranked routes:")
    for idx, scored in enumerate(evaluation.ranked_routes, 1):
        valid = "OK" if scored.is_valid else "INVALID"
        codes = ", ".join(scored.reason_codes) if scored.reason_codes else "-"
        print(
            f"    {idx}. [{valid}] {scored.route.route_id:<22} | "
            f"{scored.final_score:>7.2f} | {codes}"
        )


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


def _run_profiles(api_key=None):
    profile_a = UserPreferences(
        time_weight=8.0,
        cost_weight=1.0,
        walking_weight=2.0,
        transfer_weight=3.0,
        congestion_weight=2.0,
        reliability_weight=3.0,
    )
    profile_b = UserPreferences(
        time_weight=1.0,
        cost_weight=8.0,
        walking_weight=4.0,
        transfer_weight=2.0,
        congestion_weight=5.0,
        reliability_weight=5.0,
        max_walking_minutes=12.0,
        avoid_heavy_traffic=True,
    )

    request_a = CommuteRequest(
        user_id="demo-user",
        origin=ORIGIN,
        destination=DESTINATION,
        departure_time=DEPARTURE_TIME,
        objective="time-sensitive",
        preferences=profile_a,
        modes=["DRIVE", "TRANSIT", "WALK"],
    )
    request_b = CommuteRequest(
        user_id="demo-user",
        origin=ORIGIN,
        destination=DESTINATION,
        departure_time=DEPARTURE_TIME,
        objective="cost-and-traffic-sensitive",
        preferences=profile_b,
        modes=["DRIVE", "TRANSIT", "WALK"],
    )

    result_a = plan_commute(request_a, api_key=api_key)
    result_b = plan_commute(request_b, api_key=api_key)
    print_planner_result("PROFILE A - Time-sensitive", result_a)
    print_planner_result("PROFILE B - Cost / traffic-sensitive", result_b)

    print_banner("VERIFICATION")
    rec_a = result_a.evaluation.recommended_route if result_a.evaluation else None
    rec_b = result_b.evaluation.recommended_route if result_b.evaluation else None
    if rec_a and rec_b:
        print(f"  Profile A recommended: {rec_a.route_id}")
        print(f"  Profile B recommended: {rec_b.route_id}")
        changed = rec_a.route_id != rec_b.route_id
        print(f"  Recommendation changed with preferences: {'YES' if changed else 'NO'}")
    print(f"  Profile A historical ML used: {result_a.historical_signal_used}")
    print(f"  Profile B historical ML used: {result_b.historical_signal_used}")
    print(f"  Profile A data_sources: {result_a.data_sources}")
    print(f"  Profile B data_sources: {result_b.data_sources}")
    print()
    return result_a, result_b


def run_demo() -> None:
    _clear_cache()
    print_banner("PATCHAMOMMA - COMMUTE PLANNER ORCHESTRATOR")
    print(f"  Route: {ORIGIN}")
    print(f"     ->  {DESTINATION}")
    print(f"  Departure: {DEPARTURE_TIME}")
    print("  Historical zone IDs: not supplied (Maps-only; no Uber ward mapping)")

    if _is_live_key():
        print("\n  [LIVE MODE] Using real Google Maps Routes API.")
        _run_profiles()
        return

    print("\n  [FIXTURE MODE] GOOGLE_MAPS_API_KEY is not configured.")
    print("  Results use OFFLINE MAPS FIXTURES - not live Google Maps data.")
    print("  Historical ML is not claimed (no origin_zone / destination_zone).")

    with patch("requests.post", side_effect=_fixture_post):
        _run_profiles(api_key="MOCK_KEY_FOR_DEMO")


if __name__ == "__main__":
    run_demo()
