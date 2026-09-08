"""Mobility network capability — StaticMobilityDataRepository only."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agent.capabilities import MobilityContext
from src.network.repository import StaticMobilityDataRepository


def query_mobility_network(
    repository: Optional[StaticMobilityDataRepository],
    *,
    latitude: float,
    longitude: float,
    stop_radius_m: float = 800.0,
    station_radius_m: float = 1200.0,
    limit: int = 8,
) -> MobilityContext:
    if repository is None:
        return MobilityContext(
            network_snapshot_versions={},
            relevant_stops=[],
            relevant_stations=[],
            relevant_routes=[],
            provenance={"source": "none"},
            available=False,
            warnings=["NETWORK_REPOSITORY_UNAVAILABLE"],
        )

    stops = repository.find_stops_near(
        latitude, longitude, radius_meters=stop_radius_m, limit=limit
    )
    stations = repository.find_stations_near(
        latitude, longitude, radius_meters=station_radius_m, limit=limit
    )
    routes = repository.list_routes()[:50]

    versions: Dict[str, str] = {}
    root = getattr(repository, "root_dir", None)
    if root is not None:
        from pathlib import Path

        for dataset_dir in sorted(Path(root).iterdir()):
            if not dataset_dir.is_dir() or dataset_dir.name.startswith("."):
                continue
            snap = repository.get_active_snapshot(dataset_dir.name)
            if snap:
                versions[dataset_dir.name] = snap.version

    return MobilityContext(
        network_snapshot_versions=versions,
        relevant_stops=[s.to_dict() for s in stops],
        relevant_stations=[s.to_dict() for s in stations],
        relevant_routes=[
            {
                "id": r.id,
                "name": r.name,
                "mode": r.mode.value,
                "provider": r.provider,
                "network": r.network,
            }
            for r in routes
        ],
        provenance={
            "source": "StaticMobilityDataRepository",
            "query": {"lat": latitude, "lon": longitude},
        },
        available=True,
        warnings=[] if (stops or stations or routes or versions) else ["EMPTY_NETWORK"],
    )
