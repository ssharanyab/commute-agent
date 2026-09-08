"""
Provider-independent static mobility data repository (Phase 5A).

The planner / future Journey Builder must consume this interface only —
never GTFS files, Firestore, or a specific cloud store directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

from src.network.models import (
    FareRule,
    MobilityNetworkSnapshot,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
)


class StaticMobilityDataRepository(ABC):
    """Abstract static-network access for journey construction (future)."""

    @abstractmethod
    def find_stops_near(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_meters: float = 500.0,
        limit: int = 20,
    ) -> List[MobilityStop]:
        raise NotImplementedError

    @abstractmethod
    def find_stations_near(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_meters: float = 800.0,
        limit: int = 20,
    ) -> List[MobilityStation]:
        raise NotImplementedError

    @abstractmethod
    def get_route(self, route_id: str) -> Optional[MobilityRoute]:
        raise NotImplementedError

    @abstractmethod
    def list_routes(self, *, network: Optional[str] = None) -> List[MobilityRoute]:
        raise NotImplementedError

    @abstractmethod
    def get_stop_sequence(self, route_id: str) -> Sequence[str]:
        """Ordered stop IDs for a route (empty if unknown)."""
        raise NotImplementedError

    @abstractmethod
    def get_station_connections(self, station_id: str) -> Sequence[str]:
        """Interchange / connected station IDs."""
        raise NotImplementedError

    @abstractmethod
    def get_fare_rules(
        self,
        *,
        provider: Optional[str] = None,
        network: Optional[str] = None,
    ) -> List[FareRule]:
        raise NotImplementedError

    @abstractmethod
    def get_active_snapshot(
        self, dataset_name: str
    ) -> Optional[MobilityNetworkSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def list_snapshot_versions(
        self, dataset_name: str
    ) -> List[MobilityNetworkSnapshot]:
        raise NotImplementedError
