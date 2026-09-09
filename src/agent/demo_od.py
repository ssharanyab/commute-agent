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


# Curated landmark table for offline / demo label→coordinate resolution.
# Not a journey template; Google Geocoding is preferred when configured.
# Missing places remain unresolved unless Google (or explicit lat/lon) succeeds.
BENGALURU_LANDMARKS: Dict[str, DemoPlace] = {
    "electronic city": ELECTRONIC_CITY,
    "electronic city, bengaluru": ELECTRONIC_CITY,
    "majestic": MAJESTIC,
    "majestic, bengaluru": MAJESTIC,
    "kempegowda bus station": MAJESTIC,
    "nadaprabhu kempegowda station, majestic": MAJESTIC,
}

# Additional offline anchors for common Bengaluru labels (exact match only).
# Google Geocoding remains the primary path for arbitrary text when API key is set.
_EXTRA_LANDMARKS = {
    "indiranagar": DemoPlace("Indiranagar", "Indiranagar, Bengaluru", 12.9784, 77.6408),
    "indiranagar, bengaluru": DemoPlace(
        "Indiranagar", "Indiranagar, Bengaluru", 12.9784, 77.6408
    ),
    "jayanagar": DemoPlace("Jayanagar", "Jayanagar, Bengaluru", 12.9308, 77.5838),
    "jayanagar, bengaluru": DemoPlace(
        "Jayanagar", "Jayanagar, Bengaluru", 12.9308, 77.5838
    ),
    "silk board": DemoPlace(
        "Silk Board", "Central Silk Board, Bengaluru", 12.9177, 77.6238
    ),
    "central silk board": DemoPlace(
        "Central Silk Board", "Central Silk Board, Bengaluru", 12.9177, 77.6238
    ),
    "koramangala": DemoPlace("Koramangala", "Koramangala, Bengaluru", 12.9352, 77.6245),
    "koramangala, bengaluru": DemoPlace(
        "Koramangala", "Koramangala, Bengaluru", 12.9352, 77.6245
    ),
    "whitefield": DemoPlace("Whitefield", "Whitefield, Bengaluru", 12.9698, 77.7500),
    "whitefield, bengaluru": DemoPlace(
        "Whitefield", "Whitefield, Bengaluru", 12.9698, 77.7500
    ),
    "hsr layout": DemoPlace("HSR Layout", "HSR Layout, Bengaluru", 12.9116, 77.6473),
    "hsr": DemoPlace("HSR Layout", "HSR Layout, Bengaluru", 12.9116, 77.6473),
    "yelachenahalli": DemoPlace(
        "Yelachenahalli", "Yelachenahalli, Bengaluru", 12.8779, 77.5450
    ),
}
BENGALURU_LANDMARKS.update(_EXTRA_LANDMARKS)
