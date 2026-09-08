"""Historical mobility capability — existing XGBoost provider wrapper."""

from __future__ import annotations

from typing import Any, Optional

from src.agent.capabilities import HistoricalCapabilityResult
from src.network.historical import (
    HistoricalMobilityProvider,
    UberMovementHistoricalProvider,
)


def get_historical_context(
    *,
    origin_zone: Optional[int],
    destination_zone: Optional[int],
    hour: int,
    provider: Optional[HistoricalMobilityProvider] = None,
    journey_ref: Optional[str] = None,
) -> HistoricalCapabilityResult:
    """
    Return historical signal only when ward zones are provided.

    Never fabricates coverage when zones are missing or the model lacks data.
    """
    if origin_zone is None or destination_zone is None:
        return HistoricalCapabilityResult(
            available=False,
            coverage=False,
            journey_ref=journey_ref,
            expected_duration_minutes=None,
            reliability=None,
            deviation=None,
            confidence=None,
            provenance={"source": "historical_capability"},
            reason="INSUFFICIENT_ZONE_MAPPING",
        )

    hist = provider or UberMovementHistoricalProvider()
    result = hist.get_signal(
        origin_zone=int(origin_zone),
        destination_zone=int(destination_zone),
        hour=int(hour),
    )
    signal = dict(result.signal)
    coverage = bool(signal.get("has_historical_coverage"))
    if not coverage:
        return HistoricalCapabilityResult(
            available=True,
            coverage=False,
            journey_ref=journey_ref,
            expected_duration_minutes=None,
            reliability=None,
            deviation=None,
            confidence=None,
            provenance=result.provenance.to_dict(),
            signal=signal,
            reason="NO_HISTORICAL_COVERAGE",
        )

    return HistoricalCapabilityResult(
        available=True,
        coverage=True,
        journey_ref=journey_ref,
        expected_duration_minutes=signal.get(
            "historical_expected_travel_time_minutes"
        ),
        reliability=signal.get("reliability_score"),
        deviation=signal.get("deviation_class") or signal.get("deviation_percent"),
        confidence=result.provenance.confidence,
        provenance=result.provenance.to_dict(),
        signal=signal,
        reason="ok",
    )
