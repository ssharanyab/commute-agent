"""
Historical mobility signal helpers.

Pure, deterministic calculations for reliability, deviation, and confidence.
These do not invent live traffic and are not used as route-ranking authority.
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Deviation classification thresholds (percent vs historical expected minutes)
# ---------------------------------------------------------------------------
DEVIATION_NORMAL_MAX_PCT = 15.0
DEVIATION_ELEVATED_MAX_PCT = 30.0
DEVIATION_HIGH_MAX_PCT = 50.0

DEVIATION_NORMAL = "NORMAL"
DEVIATION_ELEVATED = "ELEVATED"
DEVIATION_HIGH = "HIGH"
DEVIATION_ANOMALOUS = "ANOMALOUS"

# ---------------------------------------------------------------------------
# Confidence labels (qualitative coverage evidence — not calibrated probabilities)
# ---------------------------------------------------------------------------
CONFIDENCE_NONE = "none"
CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

SIGNAL_SOURCE = "historical_uber_movement_ml"


def compute_historical_reliability(
    mean_seconds: Optional[float],
    std_seconds: Optional[float],
) -> Optional[float]:
    """Map historical variability to a reliability score in [0, 1].

    Uses coefficient of variation (std / mean):

        reliability = 1 / (1 + std/mean)

    Interpretation:
    - Low relative dispersion (e.g. 35 min ± 3 min) → reliability closer to 1
    - High relative dispersion (e.g. 35 min ± 12 min) → reliability closer to 0

    Returns None when inputs are missing or invalid (never fabricates).
    """
    if mean_seconds is None or std_seconds is None:
        return None
    try:
        mean_v = float(mean_seconds)
        std_v = float(std_seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(mean_v) or not math.isfinite(std_v):
        return None
    if mean_v <= 0.0 or std_v < 0.0:
        return None
    cv = std_v / mean_v
    reliability = 1.0 / (1.0 + cv)
    return round(max(0.0, min(1.0, reliability)), 4)


def compute_deviation_percent(
    current_minutes: Optional[float],
    historical_expected_minutes: Optional[float],
) -> Optional[float]:
    """(current - historical) / historical * 100.

    Returns None when historical expected time is missing, zero, or invalid,
    or when current_minutes is missing/invalid.
    """
    if current_minutes is None or historical_expected_minutes is None:
        return None
    try:
        current_v = float(current_minutes)
        hist_v = float(historical_expected_minutes)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(current_v) or not math.isfinite(hist_v):
        return None
    if hist_v <= 0.0:
        return None
    if current_v < 0.0:
        return None
    return round((current_v - hist_v) / hist_v * 100.0, 2)


def classify_deviation(deviation_percent: Optional[float]) -> Optional[str]:
    """Classify current-vs-historical delay percentage into a simple state."""
    if deviation_percent is None:
        return None
    try:
        pct = float(deviation_percent)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(pct):
        return None
    if pct <= DEVIATION_NORMAL_MAX_PCT:
        return DEVIATION_NORMAL
    if pct <= DEVIATION_ELEVATED_MAX_PCT:
        return DEVIATION_ELEVATED
    if pct <= DEVIATION_HIGH_MAX_PCT:
        return DEVIATION_HIGH
    return DEVIATION_ANOMALOUS


def resolve_confidence(
    *,
    has_historical_coverage: bool,
    std_seconds: Optional[float],
) -> str:
    """Qualitative confidence from coverage evidence (not a calibrated probability)."""
    if not has_historical_coverage:
        return CONFIDENCE_NONE
    if std_seconds is None:
        return CONFIDENCE_LOW
    try:
        std_v = float(std_seconds)
    except (TypeError, ValueError):
        return CONFIDENCE_LOW
    if not math.isfinite(std_v) or std_v < 0.0:
        return CONFIDENCE_LOW
    # Coverage plus a usable historical std estimate → high qualitative confidence.
    # (Not a calibrated probability.)
    return CONFIDENCE_HIGH
