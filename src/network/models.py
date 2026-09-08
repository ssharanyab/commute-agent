"""
Canonical static-mobility domain contracts (Phase 5A).

These models normalize provider-specific feeds into planner-ready objects.
Journey combinations are NEVER encoded here — modes are atomic concepts only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class MobilityMode(str, Enum):
    """Normalized mobility modes. Availability is city/network-specific."""

    WALK = "walk"
    BUS = "bus"
    METRO = "metro"
    AUTO_RICKSHAW = "auto_rickshaw"
    CAB = "cab"
    TWO_WHEELER = "two_wheeler"
    BIKE = "bike"
    OTHER_TRANSIT = "other_transit"


class StopType(str, Enum):
    BUS_STOP = "bus_stop"
    METRO_STATION = "metro_station"
    RAIL_STATION = "rail_station"
    AUTO_STAND = "auto_stand"
    INTERCHANGE = "interchange"
    OTHER = "other"


class SourceType(str, Enum):
    OFFICIAL_API = "official_api"
    OFFICIAL_OPEN_DATA = "official_open_data"
    GTFS = "gtfs"
    COMMUNITY_UNOFFICIAL = "community_unofficial"
    GOVERNMENT_REGULATED = "government_regulated"
    COMMERCIAL_API = "commercial_api"
    RESEARCH_DATASET = "research_dataset"
    INTERNAL_DERIVED = "internal_derived"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    FAILED = "failed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DataProvenance:
    """Reusable provenance metadata for any external or derived value."""

    source: str
    source_type: SourceType
    retrieved_at: datetime
    version: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_at: Optional[datetime] = None
    confidence: Optional[float] = None
    quality_notes: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type.value,
            "retrieved_at": self.retrieved_at.isoformat(),
            "version": self.version,
            "effective_from": self.effective_from.isoformat()
            if self.effective_from
            else None,
            "effective_at": self.effective_at.isoformat()
            if self.effective_at
            else None,
            "confidence": self.confidence,
            "quality_notes": self.quality_notes,
            "source_url": self.source_url,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "DataProvenance":
        def _dt(key: str) -> Optional[datetime]:
            raw = payload.get(key)
            if not raw:
                return None
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))

        return DataProvenance(
            source=str(payload["source"]),
            source_type=SourceType(str(payload.get("source_type", "unknown"))),
            retrieved_at=_dt("retrieved_at") or _utc_now(),
            version=payload.get("version"),
            effective_from=_dt("effective_from"),
            effective_at=_dt("effective_at"),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            quality_notes=payload.get("quality_notes"),
            source_url=payload.get("source_url"),
            notes=payload.get("notes"),
        )


@dataclass(frozen=True)
class MobilityStop:
    id: str
    name: str
    latitude: float
    longitude: float
    provider: str
    network: str
    stop_type: StopType
    provenance: DataProvenance
    accessibility: Dict[str, Any] = field(default_factory=dict)
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider,
            "network": self.network,
            "stop_type": self.stop_type.value,
            "accessibility": dict(self.accessibility),
            "source_metadata": dict(self.source_metadata),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "MobilityStop":
        return MobilityStop(
            id=str(payload["id"]),
            name=str(payload["name"]),
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
            provider=str(payload["provider"]),
            network=str(payload["network"]),
            stop_type=StopType(str(payload.get("stop_type", "other"))),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            accessibility=dict(payload.get("accessibility") or {}),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


@dataclass(frozen=True)
class MobilityRoute:
    id: str
    name: str
    provider: str
    network: str
    mode: MobilityMode
    provenance: DataProvenance
    short_name: Optional[str] = None
    stop_ids: tuple = ()
    geometry_ref: Optional[str] = None
    service_metadata: Dict[str, Any] = field(default_factory=dict)
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "short_name": self.short_name,
            "provider": self.provider,
            "network": self.network,
            "mode": self.mode.value,
            "stop_ids": list(self.stop_ids),
            "geometry_ref": self.geometry_ref,
            "service_metadata": dict(self.service_metadata),
            "source_metadata": dict(self.source_metadata),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "MobilityRoute":
        return MobilityRoute(
            id=str(payload["id"]),
            name=str(payload["name"]),
            provider=str(payload["provider"]),
            network=str(payload["network"]),
            mode=MobilityMode(str(payload["mode"])),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            short_name=payload.get("short_name"),
            stop_ids=tuple(payload.get("stop_ids") or ()),
            geometry_ref=payload.get("geometry_ref"),
            service_metadata=dict(payload.get("service_metadata") or {}),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


@dataclass(frozen=True)
class MobilityStation:
    """Metro/rail station. Coordinates optional when official source omits them."""

    id: str
    name: str
    provider: str
    provenance: DataProvenance
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    lines: tuple = ()
    line_order: Dict[str, int] = field(default_factory=dict)
    interchange_station_ids: tuple = ()
    accessibility: Dict[str, Any] = field(default_factory=dict)
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider,
            "lines": list(self.lines),
            "line_order": dict(self.line_order),
            "interchange_station_ids": list(self.interchange_station_ids),
            "accessibility": dict(self.accessibility),
            "source_metadata": dict(self.source_metadata),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "MobilityStation":
        return MobilityStation(
            id=str(payload["id"]),
            name=str(payload["name"]),
            provider=str(payload["provider"]),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
            lines=tuple(payload.get("lines") or ()),
            line_order={
                str(k): int(v) for k, v in dict(payload.get("line_order") or {}).items()
            },
            interchange_station_ids=tuple(
                payload.get("interchange_station_ids") or ()
            ),
            accessibility=dict(payload.get("accessibility") or {}),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


@dataclass(frozen=True)
class MobilityTrip:
    """GTFS-style trip. Does not invent schedules."""

    id: str
    route_id: str
    service_id: str
    provenance: DataProvenance
    headsign: Optional[str] = None
    direction_id: Optional[str] = None
    shape_id: Optional[str] = None
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "route_id": self.route_id,
            "service_id": self.service_id,
            "headsign": self.headsign,
            "direction_id": self.direction_id,
            "shape_id": self.shape_id,
            "source_metadata": dict(self.source_metadata),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "MobilityTrip":
        return MobilityTrip(
            id=str(payload["id"]),
            route_id=str(payload["route_id"]),
            service_id=str(payload["service_id"]),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            headsign=payload.get("headsign"),
            direction_id=(
                None
                if payload.get("direction_id") in (None, "")
                else str(payload.get("direction_id"))
            ),
            shape_id=(
                None
                if payload.get("shape_id") in (None, "")
                else str(payload.get("shape_id"))
            ),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


@dataclass(frozen=True)
class MobilityStopTime:
    """GTFS stop_time. Missing arrival/departure stay None — never defaulted to 00:00:00."""

    trip_id: str
    stop_id: str
    stop_sequence: int
    provenance: DataProvenance
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "stop_id": self.stop_id,
            "stop_sequence": self.stop_sequence,
            "arrival_time": self.arrival_time,
            "departure_time": self.departure_time,
            "source_metadata": dict(self.source_metadata),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "MobilityStopTime":
        def _time(key: str) -> Optional[str]:
            raw = payload.get(key)
            if raw is None:
                return None
            text = str(raw).strip()
            return text if text else None

        return MobilityStopTime(
            trip_id=str(payload["trip_id"]),
            stop_id=str(payload["stop_id"]),
            stop_sequence=int(payload["stop_sequence"]),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            arrival_time=_time("arrival_time"),
            departure_time=_time("departure_time"),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


@dataclass(frozen=True)
class FareEligibilityCondition:
    """Explicit eligibility predicate — not a gender/boolean shortcut."""

    attribute: str
    operator: str
    value: Any
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "FareEligibilityCondition":
        return FareEligibilityCondition(
            attribute=str(payload["attribute"]),
            operator=str(payload["operator"]),
            value=payload.get("value"),
            description=payload.get("description"),
        )


@dataclass(frozen=True)
class FareRule:
    """Structured fare / concession rule with provenance and effective window."""

    id: str
    provider: str
    network: str
    mode: MobilityMode
    provenance: DataProvenance
    base_fare: Optional[float] = None
    currency: str = "INR"
    rule_structure: Dict[str, Any] = field(default_factory=dict)
    eligibility: tuple = ()
    service_exclusions: tuple = ()
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "network": self.network,
            "mode": self.mode.value,
            "base_fare": self.base_fare,
            "currency": self.currency,
            "rule_structure": dict(self.rule_structure),
            "eligibility": [
                e.to_dict() if isinstance(e, FareEligibilityCondition) else e
                for e in self.eligibility
            ],
            "service_exclusions": list(self.service_exclusions),
            "effective_from": self.effective_from.isoformat()
            if self.effective_from
            else None,
            "effective_until": self.effective_until.isoformat()
            if self.effective_until
            else None,
            "version": self.version,
            "provenance": self.provenance.to_dict(),
            # Convenience mirrors for auditors (must match provenance).
            "source": self.provenance.source,
            "source_url": self.provenance.source_url,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "FareRule":
        def _dt(key: str) -> Optional[datetime]:
            raw = payload.get(key)
            if not raw:
                return None
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))

        eligibility_raw = payload.get("eligibility") or []
        eligibility = tuple(
            FareEligibilityCondition.from_dict(e)
            if isinstance(e, dict)
            else e
            for e in eligibility_raw
        )
        return FareRule(
            id=str(payload["id"]),
            provider=str(payload["provider"]),
            network=str(payload["network"]),
            mode=MobilityMode(str(payload["mode"])),
            provenance=DataProvenance.from_dict(payload["provenance"]),
            base_fare=(
                float(payload["base_fare"])
                if payload.get("base_fare") is not None
                else None
            ),
            currency=str(payload.get("currency") or "INR"),
            rule_structure=dict(payload.get("rule_structure") or {}),
            eligibility=eligibility,
            service_exclusions=tuple(payload.get("service_exclusions") or ()),
            effective_from=_dt("effective_from"),
            effective_until=_dt("effective_until"),
            version=payload.get("version"),
        )


@dataclass
class MobilityNetworkSnapshot:
    """One validated version of a static mobility dataset."""

    dataset_name: str
    provider: str
    version: str
    fetched_at: datetime
    record_count: int
    source: str
    validation_status: ValidationStatus
    provenance: DataProvenance
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    checksum: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "provider": self.provider,
            "version": self.version,
            "fetched_at": self.fetched_at.isoformat(),
            "effective_from": self.effective_from.isoformat()
            if self.effective_from
            else None,
            "effective_until": self.effective_until.isoformat()
            if self.effective_until
            else None,
            "record_count": self.record_count,
            "source": self.source,
            "validation_status": self.validation_status.value,
            "checksum": self.checksum,
            "validation_errors": list(self.validation_errors),
            "provenance": self.provenance.to_dict(),
            "payload": dict(self.payload),
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "MobilityNetworkSnapshot":
        def _dt(key: str) -> Optional[datetime]:
            value = raw.get(key)
            if not value:
                return None
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        return MobilityNetworkSnapshot(
            dataset_name=str(raw["dataset_name"]),
            provider=str(raw["provider"]),
            version=str(raw["version"]),
            fetched_at=_dt("fetched_at") or _utc_now(),
            record_count=int(raw.get("record_count") or 0),
            source=str(raw["source"]),
            validation_status=ValidationStatus(
                str(raw.get("validation_status", "pending"))
            ),
            provenance=DataProvenance.from_dict(raw["provenance"]),
            effective_from=_dt("effective_from"),
            effective_until=_dt("effective_until"),
            checksum=raw.get("checksum"),
            validation_errors=list(raw.get("validation_errors") or []),
            payload=dict(raw.get("payload") or {}),
        )
