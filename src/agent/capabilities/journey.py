"""Journey Builder capability — calls DynamicJourneyBuilder (no templates)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.journey_builder import (
    DynamicJourneyBuilder,
    JourneyBuildRequest,
    JourneyBuildResult,
    JourneyConstraints,
    SearchLimits,
)
from src.network.repository import StaticMobilityDataRepository


def build_candidate_journeys(
    repository: StaticMobilityDataRepository,
    *,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    departure_time: datetime,
    constraints: Optional[JourneyConstraints] = None,
    search_limits: Optional[SearchLimits] = None,
    builder: Optional[DynamicJourneyBuilder] = None,
    origin_endpoint=None,
    destination_endpoint=None,
) -> JourneyBuildResult:
    """Invoke the Phase 5C Journey Builder. Does not hardcode journeys."""
    jb = builder or DynamicJourneyBuilder(repository)
    request = JourneyBuildRequest(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
        departure_time=departure_time,
        constraints=constraints or JourneyConstraints(),
        search_limits=search_limits,
        origin_endpoint=origin_endpoint,
        destination_endpoint=destination_endpoint,
    )
    return jb.build(request)
