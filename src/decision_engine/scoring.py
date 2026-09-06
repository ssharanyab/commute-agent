"""
Deterministic Scoring and Constraint Validation Logic.

Normalizes candidate route attributes, evaluates hard user constraints,
computes weighted utility scores, and generates human-readable reason codes.
"""

from typing import List, Dict, Tuple, Any
from src.decision_engine.models import RouteCandidate, UserPreferences


def validate_hard_constraints(candidate: RouteCandidate, preferences: UserPreferences) -> List[str]:
    """Validate candidate route against hard user constraints.
    
    Args:
        candidate (RouteCandidate): Route candidate to check.
        preferences (UserPreferences): User constraints and weights.
        
    Returns:
        List[str]: List of violation code strings (empty if fully valid).
    """
    violations = []
    
    if preferences.max_walking_minutes is not None and candidate.walking_minutes > preferences.max_walking_minutes:
        violations.append(f"EXCEEDS_MAX_WALKING ({candidate.walking_minutes} min > {preferences.max_walking_minutes} min)")

    if preferences.max_cost is not None and candidate.cost > preferences.max_cost:
        violations.append(f"EXCEEDS_MAX_COST (INR {candidate.cost} > INR {preferences.max_cost})")

    if preferences.avoid_heavy_traffic and candidate.congestion_score >= 0.7:
        violations.append(f"HEAVY_TRAFFIC_AVOIDED (Congestion {candidate.congestion_score:.2f} >= 0.70)")

    return violations


def normalize_candidate_pool(candidates: List[RouteCandidate]) -> Dict[str, Dict[str, float]]:
    """Min-max normalize route metrics across candidate pool to scale [0.0, 1.0].
    
    Args:
        candidates (List[RouteCandidate]): Pool of candidate routes.
        
    Returns:
        Dict[str, Dict[str, float]]: Mapping of route_id to normalized metric dict.
    """
    if not candidates:
        return {}

    # Extract raw vectors
    times = [c.travel_time_minutes for c in candidates]
    costs = [c.cost for c in candidates]
    walkings = [c.walking_minutes for c in candidates]
    transfers = [c.transfers for c in candidates]
    congestions = [c.congestion_score for c in candidates]
    disruptions = [c.disruption_risk for c in candidates]
    unreliabilities = [1.0 - c.reliability_score for c in candidates]

    def min_max_scale(val: float, val_list: List[float]) -> float:
        min_v = min(val_list)
        max_v = max(val_list)
        if max_v == min_v:
            return 0.0
        return (val - min_v) / (max_v - min_v)

    normalized = {}
    for c in candidates:
        normalized[c.route_id] = {
            "travel_time": min_max_scale(c.travel_time_minutes, times),
            "cost": min_max_scale(c.cost, costs),
            "walking": min_max_scale(c.walking_minutes, walkings),
            "transfers": min_max_scale(c.transfers, transfers),
            "congestion": min_max_scale(c.congestion_score, congestions),
            "disruption": min_max_scale(c.disruption_risk, disruptions),
            "unreliability": min_max_scale(1.0 - c.reliability_score, unreliabilities)
        }

    return normalized


def calculate_route_utility(
    candidate: RouteCandidate,
    norm_metrics: Dict[str, float],
    preferences: UserPreferences,
    violations: List[str]
) -> Tuple[float, Dict[str, float]]:
    """Compute deterministic weighted utility score for a candidate route.
    
    Formula:
    Base Score = 100.0
    Weighted Penalties = sum(weight_i * normalized_metric_i)
    Utility Score = 100.0 - Weighted Penalties + Bonuses
    
    Args:
        candidate (RouteCandidate): Target candidate.
        norm_metrics (Dict[str, float]): Normalized metrics for candidate.
        preferences (UserPreferences): User trade-off weights.
        violations (List[str]): List of constraint violations for candidate.
        
    Returns:
        Tuple[float, Dict[str, float]]: (final_score, sub_scores_dict)
    """
    # 1. Calculate component penalties (all scaled by user preference weights)
    penalty_time = norm_metrics["travel_time"] * preferences.time_weight * 25.0
    penalty_cost = norm_metrics["cost"] * preferences.cost_weight * 20.0
    penalty_walking = norm_metrics["walking"] * preferences.walking_weight * 15.0
    penalty_transfers = norm_metrics["transfers"] * preferences.transfer_weight * 15.0
    penalty_congestion = norm_metrics["congestion"] * preferences.congestion_weight * 15.0
    penalty_disruption = norm_metrics["disruption"] * 10.0
    penalty_unreliability = norm_metrics["unreliability"] * preferences.reliability_weight * 15.0

    total_penalties = (
        penalty_time + penalty_cost + penalty_walking +
        penalty_transfers + penalty_congestion + penalty_disruption +
        penalty_unreliability
    )

    # 2. Preferred Mode Bonus
    bonus_preferred = 0.0
    if preferences.preferred_modes:
        pref_modes_lower = [m.lower() for m in preferences.preferred_modes]
        if candidate.mode.lower() in pref_modes_lower:
            bonus_preferred = 10.0

    # 3. Historical Mobility ML Signal Adjustment
    bonus_historical = 0.0
    sig = candidate.historical_mobility_signal
    if sig and sig.get("has_historical_coverage") is True:
        c_factor = sig.get("historical_congestion_factor", 1.0)
        if c_factor <= 1.1:
            bonus_historical = 5.0  # Verified historical free-flow corridor
        elif c_factor >= 1.4:
            bonus_historical = -5.0 # Verified historical severe bottleneck

    # 4. Final Base Score Calculation
    score = 100.0 - total_penalties + bonus_preferred + bonus_historical

    # 5. Apply Hard Constraint Penalty
    if violations:
        score -= (len(violations) * 500.0)

    sub_scores = {
        "penalty_time": penalty_time,
        "penalty_cost": penalty_cost,
        "penalty_walking": penalty_walking,
        "penalty_transfers": penalty_transfers,
        "penalty_congestion": penalty_congestion,
        "penalty_disruption": penalty_disruption,
        "penalty_unreliability": penalty_unreliability,
        "bonus_preferred": bonus_preferred,
        "bonus_historical": bonus_historical
    }

    return score, sub_scores


def generate_reason_codes(
    candidate: RouteCandidate,
    candidates: List[RouteCandidate],
    norm_metrics: Dict[str, float],
    preferences: UserPreferences,
    violations: List[str]
) -> List[str]:
    """Generate human-readable reason codes explaining why candidate scored as it did.
    
    Args:
        candidate (RouteCandidate): Candidate being evaluated.
        candidates (List[RouteCandidate]): Complete candidate pool for relative comparison.
        norm_metrics (Dict[str, float]): Normalized metrics.
        preferences (UserPreferences): User preferences.
        violations (List[str]): Constraint violations.
        
    Returns:
        List[str]: List of reason code strings.
    """
    reasons = []

    if violations:
        reasons.append("CONSTRAINT_VIOLATION")

    # Relative superiority checks across candidate pool
    min_time = min(c.travel_time_minutes for c in candidates)
    min_cost = min(c.cost for c in candidates)
    min_walking = min(c.walking_minutes for c in candidates)
    min_transfers = min(c.transfers for c in candidates)
    min_congestion = min(c.congestion_score for c in candidates)
    max_reliability = max(c.reliability_score for c in candidates)

    if candidate.travel_time_minutes == min_time:
        reasons.append("FASTEST")

    if candidate.cost == min_cost:
        reasons.append("LOW_COST")

    if candidate.walking_minutes == min_walking:
        reasons.append("LOW_WALKING")

    if candidate.transfers == min_transfers:
        reasons.append("FEWER_TRANSFERS")

    if candidate.congestion_score == min_congestion:
        reasons.append("LOW_CONGESTION")

    if candidate.reliability_score == max_reliability and candidate.reliability_score >= 0.8:
        reasons.append("HIGH_RELIABILITY")

    if preferences.preferred_modes and candidate.mode.lower() in [m.lower() for m in preferences.preferred_modes]:
        reasons.append("PREFERRED_MODE")

    sig = candidate.historical_mobility_signal
    if sig and sig.get("has_historical_coverage") is True:
        reasons.append("HISTORICAL_SUPPORT")

    return list(dict.fromkeys(reasons))  # Unique ordered list
