"""
Demo: Google Maps Routes API -> Route Evaluation Engine Integration Pipeline.

Shows the complete end-to-end flow:
  Google Maps Routes API (or mock fallback)
    -> RouteCandidate objects
    -> Route Evaluation Engine
    -> Ranked recommendation with reason codes

If GOOGLE_MAPS_API_KEY is not configured:
- A clearly labeled MOCK RUN is performed using fixture data.
- The demo explicitly states that results are NOT from live Maps data.
"""

import os
import sys
from unittest.mock import patch

from src.mobility.models import TravelMode
from src.mobility.service import get_candidate_routes, _clear_cache
from src.mobility.maps_client import MissingAPIKeyError
from src.decision_engine import evaluate_routes, UserPreferences

# Import fixture data for mock mode
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.maps_fixtures import get_drive_route_fixture, get_drive_alternative_routes_fixture, get_transit_route_fixture, get_walk_route_fixture

ORIGIN = "Electronic City Phase 1, Bengaluru"
DESTINATION = "Koramangala 4th Block, Bengaluru"
DEPARTURE_TIME = "2024-09-06T08:00:00Z"


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_result(label: str, res, candidates) -> None:
    rec = res.recommended_route
    print(f"\n[{label}]")
    print(f"Candidate Routes Evaluated: {len(candidates)}")
    if rec:
        print(f"--> RECOMMENDED: [{rec.route_id}] Mode: {rec.mode} | {rec.travel_time_minutes} min | INR {rec.cost}")
        print(f"    Score: {res.score:.2f}  |  Codes: {', '.join(res.reason_codes)}")
    else:
        print("--> No valid route found (all candidates violate hard constraints).")
    print("\n  Ranked Routes:")
    for i, sr in enumerate(res.ranked_routes, 1):
        valid = "OK" if sr.is_valid else "INVALID"
        codes = ", ".join(sr.reason_codes) if sr.reason_codes else "-"
        print(f"  {i}. [{valid}] {sr.route.route_id:<30} | {sr.final_score:>6.1f} pts | {codes}")


def run_demo() -> None:
    _clear_cache()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    is_live = bool(api_key and api_key != "your_key_here")

    print_banner("PATCHAMOMMA — GOOGLE MAPS -> ROUTE EVALUATION ENGINE DEMO")
    print(f"  Route: {ORIGIN}")
    print(f"     ->  {DESTINATION}")
    print(f"  Departure: {DEPARTURE_TIME}")

    if is_live:
        print("\n  [LIVE MODE] Using real Google Maps Routes API.")
        try:
            candidates = get_candidate_routes(
                origin=ORIGIN,
                destination=DESTINATION,
                departure_time=DEPARTURE_TIME,
                modes=[TravelMode.DRIVE, TravelMode.TRANSIT, TravelMode.WALK],
            )
        except MissingAPIKeyError as e:
            print(f"\n  [ERROR] {e}")
            return
    else:
        print("\n  [MOCK MODE] GOOGLE_MAPS_API_KEY not configured.")
        print("  Results below use FIXTURE DATA — not real Maps API responses.")
        print("  Set GOOGLE_MAPS_API_KEY in .env for live results.\n")

        drive_count = 0
        transit_count = 0
        walk_count = 0

        def fake_post(*args, **kwargs):
            import json
            body = kwargs.get("json", {})
            mode = body.get("travelMode", "DRIVE")
            nonlocal drive_count, transit_count, walk_count
            from unittest.mock import MagicMock
            m = MagicMock()
            m.status_code = 200
            if mode == "DRIVE":
                drive_count += 1
                m.json.return_value = get_drive_alternative_routes_fixture()
            elif mode == "TRANSIT":
                transit_count += 1
                m.json.return_value = get_transit_route_fixture()
            else:
                walk_count += 1
                m.json.return_value = get_walk_route_fixture()
            return m

        with patch("requests.post", side_effect=fake_post):
            candidates = get_candidate_routes(
                origin=ORIGIN,
                destination=DESTINATION,
                departure_time=DEPARTURE_TIME,
                modes=[TravelMode.DRIVE, TravelMode.TRANSIT, TravelMode.WALK],
                api_key="MOCK_KEY_FOR_DEMO",
            )

    print(f"\n  Fetched {len(candidates)} candidate route(s).")
    for c in candidates:
        cov = "YES" if (c.historical_mobility_signal and c.historical_mobility_signal.get("has_historical_coverage")) else "NO"
        print(f"  * [{c.route_id}] Mode: {c.mode:<8} | {c.travel_time_minutes} min | INR {c.cost} | "
              f"Walk: {c.walking_minutes} min | Congestion: {c.congestion_score:.2f} | ML signal: {cov}")

    if not candidates:
        print("\n  [ERROR] No candidates returned. Cannot evaluate.")
        return

    # ------------------------------------------------------------------
    # Profile A: Time-Sensitive Commuter
    # ------------------------------------------------------------------
    profile_a = UserPreferences(
        time_weight=8.0, cost_weight=1.0, walking_weight=2.0,
        transfer_weight=3.0, congestion_weight=2.0, reliability_weight=3.0
    )
    res_a = evaluate_routes(candidates, profile_a)
    print_result("PROFILE A — Time-Sensitive Commuter (fastest route prioritized)", res_a, candidates)

    # ------------------------------------------------------------------
    # Profile B: Budget & Low-Stress (max walk 12 min)
    # ------------------------------------------------------------------
    profile_b = UserPreferences(
        time_weight=1.0, cost_weight=8.0, walking_weight=4.0,
        transfer_weight=2.0, congestion_weight=5.0, reliability_weight=5.0,
        max_walking_minutes=12.0
    )
    res_b = evaluate_routes(candidates, profile_b)
    print_result("PROFILE B — Budget & Low-Stress (max walking 12 min, low cost priority)", res_b, candidates)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    print_banner("VERIFICATION")
    if candidates and res_a.recommended_route and res_b.recommended_route:
        changed = res_a.recommended_route.route_id != res_b.recommended_route.route_id
        print(f"  Profile A recommended: {res_a.recommended_route.route_id}")
        print(f"  Profile B recommended: {res_b.recommended_route.route_id}")
        print(f"  Recommendation CHANGED with preferences: {'YES' if changed else 'NO (routes identical for both profiles)'}")
    print()


if __name__ == "__main__":
    run_demo()
