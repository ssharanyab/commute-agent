"""
File-backed StaticMobilityDataRepository (replaceable MVP store).

Layout under root_dir (default: data/mobility_network/):

  <dataset>/active.json          # pointer to active version id
  <dataset>/snapshots/<ver>.json # full MobilityNetworkSnapshot payload
  <dataset>/failed/<ver>.json    # rejected snapshots (retained for audit)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.network.models import (
    FareRule,
    MobilityNetworkSnapshot,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
    ValidationStatus,
)
from src.network.repository import StaticMobilityDataRepository


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


class FileStaticMobilityRepository(StaticMobilityDataRepository):
    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    # --- paths -------------------------------------------------------------

    def _dataset_dir(self, dataset_name: str) -> Path:
        path = self.root_dir / dataset_name
        path.mkdir(parents=True, exist_ok=True)
        (path / "snapshots").mkdir(exist_ok=True)
        (path / "failed").mkdir(exist_ok=True)
        return path

    def _active_pointer(self, dataset_name: str) -> Path:
        return self._dataset_dir(dataset_name) / "active.json"

    def _snapshot_path(self, dataset_name: str, version: str) -> Path:
        return self._dataset_dir(dataset_name) / "snapshots" / f"{version}.json"

    def _failed_path(self, dataset_name: str, version: str) -> Path:
        return self._dataset_dir(dataset_name) / "failed" / f"{version}.json"

    # --- publish / rollback support ----------------------------------------

    def load_snapshot(
        self, dataset_name: str, version: str
    ) -> Optional[MobilityNetworkSnapshot]:
        path = self._snapshot_path(dataset_name, version)
        if not path.exists():
            return None
        return MobilityNetworkSnapshot.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def save_failed_snapshot(self, snapshot: MobilityNetworkSnapshot) -> Path:
        path = self._failed_path(snapshot.dataset_name, snapshot.version)
        path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def publish_snapshot(self, snapshot: MobilityNetworkSnapshot) -> None:
        """Write snapshot and mark it active. Caller must validate first."""
        if snapshot.validation_status not in {
            ValidationStatus.VALID,
            ValidationStatus.PUBLISHED,
        }:
            raise ValueError(
                f"Refusing to publish snapshot with status={snapshot.validation_status}"
            )
        published = MobilityNetworkSnapshot(
            dataset_name=snapshot.dataset_name,
            provider=snapshot.provider,
            version=snapshot.version,
            fetched_at=snapshot.fetched_at,
            record_count=snapshot.record_count,
            source=snapshot.source,
            validation_status=ValidationStatus.PUBLISHED,
            provenance=snapshot.provenance,
            effective_from=snapshot.effective_from,
            effective_until=snapshot.effective_until,
            checksum=snapshot.checksum,
            validation_errors=list(snapshot.validation_errors),
            payload=dict(snapshot.payload),
        )
        path = self._snapshot_path(published.dataset_name, published.version)
        path.write_text(
            json.dumps(published.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._active_pointer(published.dataset_name).write_text(
            json.dumps({"version": published.version}, indent=2),
            encoding="utf-8",
        )

    # --- repository API ----------------------------------------------------

    def get_active_snapshot(
        self, dataset_name: str
    ) -> Optional[MobilityNetworkSnapshot]:
        pointer = self._active_pointer(dataset_name)
        if not pointer.exists():
            return None
        meta = json.loads(pointer.read_text(encoding="utf-8"))
        version = meta.get("version")
        if not version:
            return None
        return self.load_snapshot(dataset_name, version)

    def list_snapshot_versions(
        self, dataset_name: str
    ) -> List[MobilityNetworkSnapshot]:
        snap_dir = self._dataset_dir(dataset_name) / "snapshots"
        out: List[MobilityNetworkSnapshot] = []
        for path in sorted(snap_dir.glob("*.json")):
            out.append(
                MobilityNetworkSnapshot.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            )
        return out

    def _active_payload(self, dataset_name: str) -> Dict[str, Any]:
        snap = self.get_active_snapshot(dataset_name)
        return dict(snap.payload) if snap else {}

    def _all_active_payloads(self) -> List[Dict[str, Any]]:
        payloads = []
        for dataset_dir in self.root_dir.iterdir():
            if not dataset_dir.is_dir():
                continue
            snap = self.get_active_snapshot(dataset_dir.name)
            if snap:
                payloads.append(snap.payload)
        return payloads

    def find_stops_near(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_meters: float = 500.0,
        limit: int = 20,
    ) -> List[MobilityStop]:
        scored: List[tuple] = []
        for payload in self._all_active_payloads():
            for raw in payload.get("stops") or []:
                stop = MobilityStop.from_dict(raw)
                dist = _haversine_m(
                    latitude, longitude, stop.latitude, stop.longitude
                )
                if dist <= radius_meters:
                    scored.append((dist, stop))
        scored.sort(key=lambda x: x[0])
        return [s for _, s in scored[:limit]]

    def find_stations_near(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_meters: float = 800.0,
        limit: int = 20,
    ) -> List[MobilityStation]:
        scored: List[tuple] = []
        for payload in self._all_active_payloads():
            for raw in payload.get("stations") or []:
                station = MobilityStation.from_dict(raw)
                if station.latitude is None or station.longitude is None:
                    continue  # official seeds may omit coordinates
                dist = _haversine_m(
                    latitude, longitude, station.latitude, station.longitude
                )
                if dist <= radius_meters:
                    scored.append((dist, station))
        scored.sort(key=lambda x: x[0])
        return [s for _, s in scored[:limit]]

    def get_route(self, route_id: str) -> Optional[MobilityRoute]:
        for payload in self._all_active_payloads():
            for raw in payload.get("routes") or []:
                if str(raw.get("id")) == route_id:
                    return MobilityRoute.from_dict(raw)
        return None

    def list_routes(self, *, network: Optional[str] = None) -> List[MobilityRoute]:
        routes: List[MobilityRoute] = []
        for payload in self._all_active_payloads():
            for raw in payload.get("routes") or []:
                route = MobilityRoute.from_dict(raw)
                if network is None or route.network == network:
                    routes.append(route)
        return routes

    def get_stop_sequence(self, route_id: str) -> Sequence[str]:
        route = self.get_route(route_id)
        return list(route.stop_ids) if route else []

    def get_station_connections(self, station_id: str) -> Sequence[str]:
        for payload in self._all_active_payloads():
            for raw in payload.get("stations") or []:
                if str(raw.get("id")) == station_id:
                    station = MobilityStation.from_dict(raw)
                    return list(station.interchange_station_ids)
        return []

    def get_fare_rules(
        self,
        *,
        provider: Optional[str] = None,
        network: Optional[str] = None,
    ) -> List[FareRule]:
        rules: List[FareRule] = []
        for payload in self._all_active_payloads():
            for raw in payload.get("fare_rules") or []:
                rule = FareRule.from_dict(raw)
                if provider is not None and rule.provider != provider:
                    continue
                if network is not None and rule.network != network:
                    continue
                rules.append(rule)
        return rules
