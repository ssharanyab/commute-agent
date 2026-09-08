"""Weather / context capability — structured contract, no fabrication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.agent.capabilities import ContextCapabilityResult


def get_weather_context(
    location: str,
    *,
    weather_provider: Optional[Any] = None,
) -> ContextCapabilityResult:
    """
    Return weather if a provider is configured; otherwise explicit unavailable.

    Does not invent temperature/precipitation.
    """
    if weather_provider is not None:
        payload = weather_provider(location)
        if isinstance(payload, dict) and payload.get("available"):
            return ContextCapabilityResult(
                available=True,
                weather={
                    "temperature": payload.get("temperature"),
                    "precipitation": payload.get("precipitation"),
                    "condition": payload.get("condition"),
                    "wind": payload.get("wind"),
                },
                timestamp=payload.get("timestamp")
                or datetime.now(timezone.utc).isoformat(),
                provenance={
                    "source": payload.get("source", "weather_provider"),
                },
                reason="ok",
            )
        return ContextCapabilityResult(
            available=False,
            weather=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
            provenance={"source": "weather_provider"},
            reason=str((payload or {}).get("reason", "unavailable")),
        )

    # Default: not configured (matches existing agent tool behavior).
    return ContextCapabilityResult(
        available=False,
        weather=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
        provenance={"source": "weather", "location": location},
        reason="not_configured",
    )
