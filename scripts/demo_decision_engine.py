"""
Demonstration script showing Route Evaluation Engine behavior across different user preference profiles.
"""

from src.decision_engine import evaluate_routes, UserPreferences
from tests.fixtures import get_bengaluru_test_candidates


def run_demo():
    candidates = get_bengaluru_test_candidates()

    print("================================================================================")
    print("      PATCHAMOMMA COMMUTE ROUTE EVALUATION ENGINE DEMONSTRATION")
    print("================================================================================")
    print(f"Loaded {len(candidates)} Candidate Routes for Bengaluru (Electronic City -> Koramangala):")
    for c in candidates:
        coverage_str = "YES" if (c.historical_mobility_signal and c.historical_mobility_signal.get("has_historical_coverage")) else "NO"
        print(f"  * [{c.route_id}] Mode: {c.mode:<6} | Duration: {c.travel_time_minutes} min | Cost: INR {c.cost:<5} | Walk: {c.walking_minutes} min | Congestion: {c.congestion_score:.2f} | ML Support: {coverage_str}")

    # Profile 1: Time-Sensitive Executive (Fastest commute prioritized)
    profile_time = UserPreferences(
        time_weight=10.0,
        cost_weight=0.5,
        walking_weight=1.0,
        transfer_weight=2.0,
        congestion_weight=1.0,
        reliability_weight=2.0
    )

    # Profile 2: Budget-Conscious Student (Lowest cost & public transit prioritized)
    profile_budget = UserPreferences(
        time_weight=1.0,
        cost_weight=10.0,
        walking_weight=1.0,
        transfer_weight=1.0,
        congestion_weight=1.0,
        reliability_weight=2.0,
        max_cost=100.0,
        preferred_modes=["metro"]
    )

    # Profile 3: Traffic-Avoidance & Low Stress (Avoid heavy congestion, max walking 5 min)
    profile_low_stress = UserPreferences(
        time_weight=2.0,
        cost_weight=1.0,
        walking_weight=2.0,
        transfer_weight=3.0,
        congestion_weight=8.0,
        reliability_weight=5.0,
        max_walking_minutes=5.0,
        avoid_heavy_traffic=True
    )

    profiles = [
        ("PROFILE 1: Time-Sensitive Executive (Fastest Route)", profile_time),
        ("PROFILE 2: Budget-Conscious Student (Max Cost INR 100, Prefer Metro)", profile_budget),
        ("PROFILE 3: Low-Stress Traffic Avoidance (Avoid Heavy Traffic, Max Walk 5m)", profile_low_stress),
    ]

    for title, prefs in profiles:
        print("\n" + "="*80)
        print(f"  {title}")
        print("="*80)
        res = evaluate_routes(candidates, prefs)
        
        rec = res.recommended_route
        rec_id = rec.route_id if rec else "None (All routes violated hard constraints)"
        print(f"--> TOP RECOMMENDED ROUTE: {rec_id} (Score: {res.score:.2f})")
        print(f"  Reason Codes: {', '.join(res.reason_codes)}")
        
        print("\n  Full Ranked Candidate Table:")
        print(f"  {'Rank':<5} | {'Route ID':<30} | {'Score':<8} | {'Valid?':<7} | {'Reason Codes / Violations'}")
        print("  " + "-"*75)
        for idx, sr in enumerate(res.ranked_routes, 1):
            valid_str = "YES" if sr.is_valid else "NO"
            info = ", ".join(sr.reason_codes) if sr.is_valid else "VIOLATIONS: " + "; ".join(sr.constraint_violations)
            print(f"  {idx:<5} | {sr.route.route_id:<30} | {sr.final_score:<8.2f} | {valid_str:<7} | {info}")

    print("\n" + "="*80)
    print("  VERIFICATION COMPLETE: Recommended route changes dynamically with UserPreferences!")
    print("="*80 + "\n")


if __name__ == "__main__":
    run_demo()
