"""
Mobility Service Module.

High-level interface that orchestrates Maps API calls, in-process caching,
response parsing, and RouteCandidate conversion.

Usage:
    candidates = get_candidate_routes(
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        departure_time="2024-09-06T08:00:00Z",
        modes=[TravelMode.DRIVE, TravelMode.TRANSIT]
    )
"""

import os
import time
import logging
from typing import List, Optional, Dict, Tuple, Any

from src.mobility.models import MapsRouteRequest, TravelMode
from src.mobility.maps_client import MapsClient, MapsAPIError, MissingAPIKeyError, NoRoutesFoundError
from src.mobility.route_adapter import adapt_maps_response
from src.decision_engine.models import RouteCandidate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process TTL cache
# ---------------------------------------------------------------------------

_cache: Dict[str, Tuple[float, List]] = {}  # key -> (expiry_timestamp, results)

DEFAULT_CACHE_TTL = int(os.environ.get("MAPS_CACHE_TTL_SECONDS", "300"))


def _cache_get(key: str) -> Optional[List]:
    """Return cached results if still valid, otherwise None."""
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _cache_set(key: str, value: List, ttl: int = DEFAULT_CACHE_TTL) -> None:
    """Store results in cache with expiry."""
    _cache[key] = (time.monotonic() + ttl, value)


def _clear_cache() -> None:
    """Clear all cached entries (used in tests)."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Service interface
# ---------------------------------------------------------------------------

def get_candidate_routes(
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
    modes: Optional[List[TravelMode]] = None,
    cache_ttl: int = DEFAULT_CACHE_TTL,
    api_key: Optional[str] = None,
) -> List[RouteCandidate]:
    """Retrieve candidate commute routes from Google Maps Routes API.

    Queries each requested travel mode separately, converts responses into
    RouteCandidate objects, and returns the combined list for the Route
    Evaluation Engine to rank.

    Args:
        origin (str): Origin address or "lat,lng" string.
        destination (str): Destination address or "lat,lng" string.
        departure_time (Optional[str]): ISO 8601 departure time or None for now.
        modes (Optional[List[TravelMode]]): Travel modes to query.
                Defaults to [DRIVE, TRANSIT].
        cache_ttl (int): Cache TTL in seconds.
        api_key (Optional[str]): Override API key (for testing only).

    Returns:
        List[RouteCandidate]: Candidates ready for the Route Evaluation Engine.

    Raises:
        MissingAPIKeyError: If GOOGLE_MAPS_API_KEY is not configured.
        MapsAPIError: For unrecoverable Maps API failures.
    """
    if modes is None:
        modes = [TravelMode.DRIVE, TravelMode.TRANSIT]

    client = MapsClient(api_key=api_key)
    candidates: List[RouteCandidate] = []

    for mode in modes:
        request = MapsRouteRequest(
            origin=origin,
            destination=destination,
            mode=mode,
            departure_time=departure_time,
            compute_alternatives=True,
        )
        cache_key = request.cache_key()
        cached = _cache_get(cache_key)

        if cached is not None:
            logger.debug("Cache hit for %s", cache_key)
            candidates.extend(cached)
            continue

        try:
            responses = client.compute_routes(request)
            mode_candidates = [adapt_maps_response(r) for r in responses]
            _cache_set(cache_key, mode_candidates, ttl=cache_ttl)
            candidates.extend(mode_candidates)
            logger.info("Fetched %d %s routes from Maps API.", len(mode_candidates), mode.value)

        except NoRoutesFoundError as e:
            logger.warning("No %s routes: %s", mode.value, e)
            # Not fatal — other modes may still provide candidates
        except MapsAPIError as e:
            logger.error("Maps API error for mode %s: %s", mode.value, e)
            raise

    return candidates
