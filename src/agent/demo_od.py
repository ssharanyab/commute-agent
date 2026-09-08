"""
Demo / test place anchors for Bengaluru (Phase 5D).

These are geocoding aids for tests and demos — NOT production route special-cases
and NOT journey templates. Any OD may be supplied at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple


@dataclass(frozen=True)
class DemoPlace:
    name: str
    address: str
    latitude: float
    longitude: float


# Canonical demo OD for Patchamomma / Phase 5D integration scenarios.
ELECTRONIC_CITY = DemoPlace(
    name="Electronic City",
    address="Electronic City, Bengaluru",
    latitude=12.8452,
    longitude=77.6602,
)

MAJESTIC = DemoPlace(
    name="Majestic",
    address="Majestic, Bengaluru",
    latitude=12.9767,
    longitude=77.5713,
)

CANONICAL_DEMO_OD: Tuple[DemoPlace, DemoPlace] = (ELECTRONIC_CITY, MAJESTIC)

# Deterministic demo departure used in integration tests.
CANONICAL_DEMO_DEPARTURE = datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc)


# Curated landmark table for optional label→coordinate resolution in tests/demos.
# Not a journey template; missing places simply remain unresolved.
BENGALURU_LANDMARKS: Dict[str, DemoPlace] = {
    "electronic city": ELECTRONIC_CITY,
    "electronic city, bengaluru": ELECTRONIC_CITY,
    "majestic": MAJESTIC,
    "majestic, bengaluru": MAJESTIC,
    "kempegowda bus station": MAJESTIC,
    "nadaprabhu kempegowda station, majestic": MAJESTIC,
}
