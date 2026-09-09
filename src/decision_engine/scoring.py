"""
Deterministic Scoring and Constraint Validation Logic.

Normalizes candidate route attributes, evaluates hard user constraints,
computes weighted utility scores, and generates human-readable reason codes.

Scoring answers: "best route for THIS user's weights" — not "fastest route".
No mode-specific penalties (e.g. no cab penalty). Historical mobility signals
supplement Maps duration; missing coverage never fabricates values or penalties.
"""

from __future__ import annotations

from typing import List, Dict, Tuple, Any, Optional, Set

from src.decision_engine.models import (
    RouteCandidate,
    UserPreferences,
    ScoredRoute,
    RouteCategory,
    CATEGORY_BEST_OVERALL,
    CATEGORY_FASTEST,
    CATEGORY_CHEAPEST,
    CATEGORY_MOST_RELIABLE,
)
from src.historical_signal import (
    DEVIATION_NORMAL,
    DEVIATION_ELEVATED,
    DEVIATION_HIGH,
    DEVIATION_ANOMALOUS,
    compute_deviation_percent,
    classify_deviation,
)

# Modes that share the same hard-exclusion family (DRIVE adapts to "cab").
_CAB_FAMILY: Set[str] = {"cab", "taxi", "drive", "rideshare", "uber", "ola"}
# User-facing "auto" must cover the canonical network token auto_rickshaw.
_AUTO_FAMILY: Set[str] = {"auto", "auto_rickshaw", "rickshaw", "tuk_tuk", "tuk-tuk"}

# ---------------------------------------------------------------------------
# Normalization / scoring constants (named — not scattered magic numbers)
# ---------------------------------------------------------------------------
# Absolute references dampen binary min-max swings for mode-intrinsic zeros
# (cab/drive often have 0 walking and 0 transfers vs transit).
WALKING_REF_MINUTES = 15.0
TRANSFER_REF_COUNT = 2.0
HYBRID_POOL_WEIGHT = 0.5  # blend of pool min-max vs absolute reference

# Relative preference weights allocate this shared penalty budget.
WEIGHTED_PENALTY_BUDGET = 80.0
# Mild disruption term outside user-weight renormalization.
DISRUPTION_PENALTY_SCALE = 8.0
PREFERRED_MODE_BONUS = 10.0

# Historical soft adjustments (only when coverage + real values exist)
HIST_STABLE_RELIABILITY_MIN = 0.75
HIST_STABLE_BONUS = 5.0
HIST_DEVIATION_PENALTY = {
    DEVIATION_NORMAL: 0.0,
    DEVIATION_ELEVATED: 3.0,
    DEVIATION_HIGH: 6.0,
    DEVIATION_ANOMALOUS: 10.0,
}
HIST_NEAR_TYPICAL_BONUS = 2.0


def _normalize_mode_token(mode: str) -> str:
    return (mode or "").strip().lower()


def expand_excluded_mode_tokens(excluded_modes: Optional[List[str]]) -> Set[str]:
    """Expand user exclusion tokens to the full matching set used by validation."""
    expanded: Set[str] = set()
    if not excluded_modes:
        return expanded
    for raw in excluded_modes:
        token = _normalize_mode_token(raw)
        if not token:
            continue
        if token in _CAB_FAMILY or token in {"cabs", "taxis"}:
            expanded.update(_CAB_FAMILY)
        elif token in _AUTO_FAMILY:
            expanded.update(_AUTO_FAMILY)
        else:
            expanded.add(token)
    return expanded


def mode_is_excluded(candidate_mode: str, excluded_modes: Optional[List[str]]) -> bool:
    """True when candidate mode is covered by a hard exclusion."""
    expanded = expand_excluded_mode_tokens(excluded_modes)
    if not expanded:
        return False
    return _normalize_mode_token(candidate_mode) in expanded


def validate_hard_constraints(candidate: RouteCandidate, preferences: UserPreferences) -> List[str]:
    """Validate candidate route against hard user constraints.

    Args:
        candidate (RouteCandidate): Route candidate to check.
        preferences (UserPreferences): User constraints and weights.

    Returns:
        List[str]: List of violation code strings (empty if fully valid).
    """
    violations = []

    modes_to_check = list(candidate.component_modes or [])
    if candidate.mode and candidate.mode not in modes_to_check:
        modes_to_check.append(candidate.mode)
    for mode_token in modes_to_check:
        if mode_is_excluded(mode_token, preferences.excluded_modes):
            violations.append(
                f"EXCLUDED_MODE ({mode_token} excluded by user constraint)"
            )
            break

    if preferences.max_walking_minutes is not None and candidate.walking_minutes > preferences.max_walking_minutes:
        violations.append(
            f"EXCEEDS_MAX_WALKING ({candidate.walking_minutes} min > {preferences.max_walking_minutes} min)"
        )

    if preferences.max_cost is not None:
        # Unknown cost must not be treated as ₹0 against a max_cost cap.
        if getattr(candidate, "cost_status", "known") == "known":
            if candidate.cost > preferences.max_cost:
                violations.append(
                    f"EXCEEDS_MAX_COST (INR {candidate.cost} > INR {preferences.max_cost})"
                )
    if preferences.avoid_heavy_traffic and candidate.congestion_score >= 0.7:
        violations.append(
            f"HEAVY_TRAFFIC_AVOIDED (Congestion {candidate.congestion_score:.2f} >= 0.70)"
        )

    return violations


def _min_max_scale(val: float, val_list: List[float]) -> float:
    min_v = min(val_list)
    max_v = max(val_list)
    if max_v == min_v:
        return 0.0
    return (val - min_v) / (max_v - min_v)


def _hybrid_norm(val: float, val_list: List[float], absolute_norm: float) -> float:
    """Blend pool-relative min-max with an absolute reference scale."""
    pool = _min_max_scale(val, val_list)
    abs_n = max(0.0, min(1.0, absolute_norm))
    return HYBRID_POOL_WEIGHT * pool + (1.0 - HYBRID_POOL_WEIGHT) * abs_n


def _historical_expected_minutes(sig: Optional[Dict[str, Any]]) -> Optional[float]:
    if not sig or sig.get("has_historical_coverage") is not True:
        return None
    for key in (
        "historical_expected_travel_time_minutes",
        "historical_typical_travel_time_minutes",
    ):
        raw = sig.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0.0:
            return val
    return None


def effective_reliability(candidate: RouteCandidate) -> float:
    """Maps heuristic reliability, optionally blended with historical stability.

    Missing historical coverage / missing std → use candidate.reliability_score only.
    Never fabricates historical reliability.
    """
    base = float(candidate.reliability_score)
    sig = candidate.historical_mobility_signal
    if not sig or sig.get("has_historical_coverage") is not True:
        return max(0.0, min(1.0, base))
    hist_rel = sig.get("historical_reliability_score")
    if hist_rel is None:
        return max(0.0, min(1.0, base))
    try:
        hist_v = float(hist_rel)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, base))
    if hist_v < 0.0 or hist_v > 1.0:
        return max(0.0, min(1.0, base))
    blended = 0.5 * base + 0.5 * hist_v
    return max(0.0, min(1.0, blended))


def route_deviation_state(candidate: RouteCandidate) -> Tuple[Optional[float], Optional[str]]:
    """Current Maps duration vs historical expected (when coverage exists)."""
    sig = candidate.historical_mobility_signal
    hist = _historical_expected_minutes(sig)
    if hist is None:
        # Prefer precomputed signal fields when present
        if sig and sig.get("has_historical_coverage") is True:
            pct = sig.get("deviation_percent")
            state = sig.get("deviation_state")
            if pct is not None or state is not None:
                try:
                    pct_f = float(pct) if pct is not None else None
                except (TypeError, ValueError):
                    pct_f = None
                return pct_f, state if isinstance(state, str) else classify_deviation(pct_f)
        return None, None
    pct = compute_deviation_percent(candidate.travel_time_minutes, hist)
    return pct, classify_deviation(pct)


def normalize_candidate_pool(candidates: List[RouteCandidate]) -> Dict[str, Dict[str, float]]:
    """Normalize route metrics across the candidate pool to [0.0, 1.0].

    Time/cost/congestion/reliability/disruption use pool min-max.
    Walking/transfers use a hybrid of min-max and absolute references so that
    mode-intrinsic zeros (typical of cab/drive) do not automatically consume
    the full penalty range against transit.
    """
    if not candidates:
        return {}

    times = [c.travel_time_minutes for c in candidates]
    # Unknown cost is NEUTRAL: excluded from cost pool; norm cost = 0 (no penalty).
    known_costs = [
        c.cost
        for c in candidates
        if getattr(c, "cost_status", "known") == "known"
    ]
    costs = known_costs if known_costs else [0.0]
    walkings = [c.walking_minutes for c in candidates]
    transfers = [float(c.transfers) for c in candidates]
    congestions = [c.congestion_score for c in candidates]
    disruptions = [c.disruption_risk for c in candidates]
    reliabilities = [effective_reliability(c) for c in candidates]
    unreliabilities = [1.0 - r for r in reliabilities]

    normalized: Dict[str, Dict[str, float]] = {}
    for c in candidates:
        walk_abs = c.walking_minutes / WALKING_REF_MINUTES if WALKING_REF_MINUTES > 0 else 0.0
        xfer_abs = float(c.transfers) / TRANSFER_REF_COUNT if TRANSFER_REF_COUNT > 0 else 0.0
        eff_rel = effective_reliability(c)
        if getattr(c, "cost_status", "known") == "known" and known_costs:
            cost_norm = _min_max_scale(c.cost, known_costs)
        else:
            # Neutral mid-scale: not rewarded as free (0), not punished as max.
            cost_norm = 0.5
        normalized[c.route_id] = {
            "travel_time": _min_max_scale(c.travel_time_minutes, times),
            "cost": cost_norm,
            "walking": _hybrid_norm(c.walking_minutes, walkings, walk_abs),
            "transfers": _hybrid_norm(float(c.transfers), transfers, xfer_abs),
            "congestion": _min_max_scale(c.congestion_score, congestions),
            "disruption": _min_max_scale(c.disruption_risk, disruptions),
            "unreliability": _min_max_scale(1.0 - eff_rel, unreliabilities),
            "effective_reliability": eff_rel,
        }

    return normalized


def _preference_weight_shares(preferences: UserPreferences) -> Dict[str, float]:
    """Convert raw preference weights into shares that sum to 1.0."""
    raw = {
        "travel_time": max(0.0, float(preferences.time_weight)),
        "cost": max(0.0, float(preferences.cost_weight)),
        "walking": max(0.0, float(preferences.walking_weight)),
        "transfers": max(0.0, float(preferences.transfer_weight)),
        "congestion": max(0.0, float(preferences.congestion_weight)),
        "unreliability": max(0.0, float(preferences.reliability_weight)),
    }
    total = sum(raw.values())
    if total <= 0.0:
        n = float(len(raw))
        return {k: 1.0 / n for k in raw}
    return {k: v / total for k, v in raw.items()}


def _historical_score_delta(
    candidate: RouteCandidate,
    preferences: UserPreferences,
) -> Tuple[float, Dict[str, float]]:
    """Soft historical adjustments. Missing coverage → zero delta (no penalty)."""
    details = {
        "bonus_historical_stable": 0.0,
        "bonus_historical_near_typical": 0.0,
        "penalty_historical_deviation": 0.0,
    }
    sig = candidate.historical_mobility_signal
    if not sig or sig.get("has_historical_coverage") is not True:
        return 0.0, details

    shares = _preference_weight_shares(preferences)
    # Stability / deviation matter most when user weights reliability (and congestion).
    hist_scale = max(shares["unreliability"], shares["congestion"])

    hist_rel = sig.get("historical_reliability_score")
    if hist_rel is not None:
        try:
            hist_v = float(hist_rel)
        except (TypeError, ValueError):
            hist_v = None
        if hist_v is not None and hist_v >= HIST_STABLE_RELIABILITY_MIN:
            details["bonus_historical_stable"] = HIST_STABLE_BONUS * (0.5 + hist_scale)

    _pct, state = route_deviation_state(candidate)
    if state == DEVIATION_NORMAL:
        details["bonus_historical_near_typical"] = HIST_NEAR_TYPICAL_BONUS * (0.5 + hist_scale)
    elif state in HIST_DEVIATION_PENALTY:
        details["penalty_historical_deviation"] = (
            HIST_DEVIATION_PENALTY[state] * (0.5 + hist_scale)
        )

    delta = (
        details["bonus_historical_stable"]
        + details["bonus_historical_near_typical"]
        - details["penalty_historical_deviation"]
    )
    return delta, details


def calculate_route_utility(
    candidate: RouteCandidate,
    norm_metrics: Dict[str, float],
    preferences: UserPreferences,
    violations: List[str],
) -> Tuple[float, Dict[str, float]]:
    """Compute deterministic weighted utility score for a candidate route.

    Formula:
      shares = preference_weights / sum(weights)
      WeightedPenalties = sum(share_i * WEIGHTED_PENALTY_BUDGET * norm_i)
      + disruption term
      Score = 100 - penalties + preferred_mode_bonus + historical_delta
      - hard constraint penalties
    """
    shares = _preference_weight_shares(preferences)

    penalty_time = shares["travel_time"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["travel_time"]
    penalty_cost = shares["cost"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["cost"]
    penalty_walking = shares["walking"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["walking"]
    penalty_transfers = shares["transfers"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["transfers"]
    penalty_congestion = shares["congestion"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["congestion"]
    penalty_unreliability = (
        shares["unreliability"] * WEIGHTED_PENALTY_BUDGET * norm_metrics["unreliability"]
    )
    penalty_disruption = norm_metrics["disruption"] * DISRUPTION_PENALTY_SCALE

    total_penalties = (
        penalty_time
        + penalty_cost
        + penalty_walking
        + penalty_transfers
        + penalty_congestion
        + penalty_disruption
        + penalty_unreliability
    )

    bonus_preferred = 0.0
    if preferences.preferred_modes:
        pref_modes_lower = [m.lower() for m in preferences.preferred_modes]
        if candidate.mode.lower() in pref_modes_lower:
            bonus_preferred = PREFERRED_MODE_BONUS

    hist_delta, hist_details = _historical_score_delta(candidate, preferences)

    score = 100.0 - total_penalties + bonus_preferred + hist_delta

    if violations:
        score -= len(violations) * 500.0

    sub_scores = {
        "penalty_time": penalty_time,
        "penalty_cost": penalty_cost,
        "penalty_walking": penalty_walking,
        "penalty_transfers": penalty_transfers,
        "penalty_congestion": penalty_congestion,
        "penalty_disruption": penalty_disruption,
        "penalty_unreliability": penalty_unreliability,
        "bonus_preferred": bonus_preferred,
        "bonus_historical": hist_delta,  # backward-compatible aggregate
        **hist_details,
    }

    return score, sub_scores


def generate_reason_codes(
    candidate: RouteCandidate,
    candidates: List[RouteCandidate],
    norm_metrics: Dict[str, float],
    preferences: UserPreferences,
    violations: List[str],
) -> List[str]:
    """Generate reason codes from actual route attributes only."""
    reasons: List[str] = []

    if violations:
        reasons.append("CONSTRAINT_VIOLATION")

    min_time = min(c.travel_time_minutes for c in candidates)
    known_cost_candidates = [
        c for c in candidates if getattr(c, "cost_status", "known") == "known"
    ]
    min_cost = (
        min(c.cost for c in known_cost_candidates) if known_cost_candidates else None
    )
    min_walking = min(c.walking_minutes for c in candidates)
    min_transfers = min(c.transfers for c in candidates)
    min_congestion = min(c.congestion_score for c in candidates)
    max_eff_rel = max(effective_reliability(c) for c in candidates)

    if candidate.travel_time_minutes == min_time:
        reasons.append("FASTEST")

    if (
        min_cost is not None
        and getattr(candidate, "cost_status", "known") == "known"
        and candidate.cost == min_cost
    ):
        reasons.append("LOW_COST")
    if candidate.walking_minutes == min_walking:
        reasons.append("LOW_WALKING")

    if candidate.transfers == min_transfers:
        reasons.append("FEWER_TRANSFERS")

    if candidate.congestion_score == min_congestion:
        reasons.append("LOW_CONGESTION")

    eff_rel = effective_reliability(candidate)
    if eff_rel == max_eff_rel and eff_rel >= 0.8:
        reasons.append("HIGH_RELIABILITY")

    if preferences.preferred_modes and candidate.mode.lower() in [
        m.lower() for m in preferences.preferred_modes
    ]:
        reasons.append("PREFERRED_MODE")

    sig = candidate.historical_mobility_signal
    if sig and sig.get("has_historical_coverage") is True:
        reasons.append("HISTORICAL_SUPPORT")
        hist_rel = sig.get("historical_reliability_score")
        try:
            hist_v = float(hist_rel) if hist_rel is not None else None
        except (TypeError, ValueError):
            hist_v = None
        if hist_v is not None and hist_v >= HIST_STABLE_RELIABILITY_MIN:
            reasons.append("HISTORICALLY_STABLE")

        _pct, state = route_deviation_state(candidate)
        if state == DEVIATION_NORMAL:
            reasons.append("CURRENTLY_NEAR_TYPICAL")
        elif state in (DEVIATION_ELEVATED, DEVIATION_HIGH, DEVIATION_ANOMALOUS):
            reasons.append("CURRENTLY_ABOVE_TYPICAL")

    return list(dict.fromkeys(reasons))


def build_route_categories(
    valid_ranked: List[ScoredRoute],
    recommended: Optional[ScoredRoute],
) -> List[RouteCategory]:
    """Derive BEST_OVERALL / FASTEST / CHEAPEST / MOST_RELIABLE from valid candidates.

    Categories are omitted when no valid candidate exists.
    """
    if not valid_ranked or recommended is None:
        return []

    fastest = min(
        valid_ranked,
        key=lambda sr: (sr.route.travel_time_minutes, sr.route.route_id),
    )
    known_cost = [
        sr
        for sr in valid_ranked
        if getattr(sr.route, "cost_status", "known") == "known"
    ]
    cheapest = min(
        known_cost if known_cost else valid_ranked,
        key=lambda sr: (
            sr.route.cost if getattr(sr.route, "cost_status", "known") == "known" else float("inf"),
            sr.route.route_id,
        ),
    )
    most_reliable = sorted(
        valid_ranked,
        key=lambda sr: (-effective_reliability(sr.route), sr.route.route_id),
    )[0]

    return [
        RouteCategory(category=CATEGORY_BEST_OVERALL, route=recommended.route),
        RouteCategory(category=CATEGORY_FASTEST, route=fastest.route),
        RouteCategory(category=CATEGORY_CHEAPEST, route=cheapest.route),
        RouteCategory(category=CATEGORY_MOST_RELIABLE, route=most_reliable.route),
    ]


def unique_category_alternatives(
    categories: List[RouteCategory],
    recommended_route_id: Optional[str],
) -> List[RouteCategory]:
    """Category entries whose route is not the overall recommendation (no duplicate routes)."""
    seen: Set[str] = set()
    if recommended_route_id:
        seen.add(recommended_route_id)
    out: List[RouteCategory] = []
    for item in categories:
        if item.category == CATEGORY_BEST_OVERALL:
            continue
        if item.route.route_id in seen:
            continue
        seen.add(item.route.route_id)
        out.append(item)
    return out
