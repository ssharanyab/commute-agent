"""
Test Fixtures for Bengaluru Commute Decision Engine.

THIS IS A LOCAL TEST/DEMO FIXTURE FILE, NOT PRODUCTION MOBILITY DATA.
Provides realistic candidate routes for Electronic City -> Koramangala commute.
"""

from src.decision_engine.models import RouteCandidate


def get_bengaluru_test_candidates() -> list[RouteCandidate]:
    """Return 3 realistic candidate routes for Bengaluru commute (Electronic City to Koramangala).

    Returns:
        list[RouteCandidate]: List of candidate routes.
    """
    candidate_1 = RouteCandidate(
        route_id="bengaluru_cab_express",
        mode="cab",
        travel_time_minutes=32.0,
        cost=350.0,
        walking_minutes=2.0,
        transfers=0,
        congestion_score=0.75,
        reliability_score=0.70,
        disruption_risk=0.15,
        historical_mobility_signal={
            "signal_source": "historical_uber_movement_ml",
            "has_historical_coverage": True,
            "historical_coverage": True,
            "historical_typical_travel_time_minutes": 33.5,
            "historical_expected_travel_time_minutes": 33.5,
            "historical_congestion_factor": 1.45,
            "historical_std_travel_time_minutes": 12.0,
            "historical_reliability_score": 0.55,
            "confidence_level": "high",
        },
    )

    candidate_2 = RouteCandidate(
        route_id="bengaluru_bmtc_metro_transit",
        mode="metro",
        travel_time_minutes=48.0,
        cost=45.0,
        walking_minutes=9.0,
        transfers=1,
        congestion_score=0.20,
        reliability_score=0.92,
        disruption_risk=0.05,
        historical_mobility_signal={
            "signal_source": "historical_uber_movement_ml",
            "has_historical_coverage": False,
            "historical_coverage": False,
            "confidence_level": "none",
        },
    )

    candidate_3 = RouteCandidate(
        route_id="bengaluru_auto_arterial",
        mode="auto",
        travel_time_minutes=40.0,
        cost=180.0,
        walking_minutes=3.0,
        transfers=0,
        congestion_score=0.45,
        reliability_score=0.80,
        disruption_risk=0.10,
        historical_mobility_signal={
            "signal_source": "historical_uber_movement_ml",
            "has_historical_coverage": True,
            "historical_coverage": True,
            "historical_typical_travel_time_minutes": 39.0,
            "historical_expected_travel_time_minutes": 39.0,
            "historical_congestion_factor": 1.15,
            "historical_std_travel_time_minutes": 4.0,
            "historical_reliability_score": 0.88,
            "confidence_level": "high",
        },
    )

    return [candidate_1, candidate_2, candidate_3]
