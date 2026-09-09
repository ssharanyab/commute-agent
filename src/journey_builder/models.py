"""
Journey Builder domain models (Phase 5C / 6D).

Journeys are ordered sequences of concrete legs with network references.
Atomic modes are domain concepts; journey *combinations* are never templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.network.models import DataProvenance, MobilityMode


class NodeKind(str, Enum):
    ORIGIN = "origin"
    DESTINATION = "destination"
    BUS_STOP = "bus_stop"
    METRO_STATION = "metro_station"
    INTERCHANGE = "interchange"
    OTHER = "other"


class EdgeKind(str, Enum):
    WALK = "walk"
    BUS = "bus"
    METRO = "metro"
    INTERCHANGE = "interchange"
    ROAD_ACCESS = "road_access"  # cab/auto — geometry deferred to enrichment
    ROAD_DIRECT = "road_direct"  # full OD road (cab/auto)
    TRANSFER_WALK = "transfer_walk"


class SegmentRole(str, Enum):
    """Semantic role of a leg within a composed journey (not a search template)."""

    ACCESS = "access"
    TRANSIT = "transit"
    TRANSFER = "transfer"
    EGRESS = "egress"
    FULL_JOURNEY_ROAD = "full_journey_road"
    OTHER = "other"


class ValueStatus(str, Enum):
    """Distinguish known / unknown / unavailable (do not confuse these)."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider: Optional[str] = None
    network: Optional[str] = None
    source_ref: Optional[str] = None  # underlying stop/station id
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider,
            "network": self.network,
            "source_ref": self.source_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphEdge:
    id: str
    from_node: str
    to_node: str
    kind: EdgeKind
    mode: MobilityMode
    provider: Optional[str] = None
    route_id: Optional[str] = None
    distance_meters: Optional[float] = None
    is_transfer: bool = False
    needs_enrichment: bool = False
    confidence: Optional[float] = None
    provenance: Optional[DataProvenance] = None
    schedule_meta: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "kind": self.kind.value,
            "mode": self.mode.value,
            "provider": self.provider,
            "route_id": self.route_id,
            "distance_meters": self.distance_meters,
            "is_transfer": self.is_transfer,
            "needs_enrichment": self.needs_enrichment,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "schedule_meta": dict(self.schedule_meta),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EnrichmentRequirement:
    """Boundary for live routing — no Google calls inside the graph search."""

    requirement_type: str  # e.g. road_geometry_time
    leg_index: int
    mode: str
    from_lat: Optional[float]
    from_lon: Optional[float]
    to_lat: Optional[float]
    to_lon: Optional[float]
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_type": self.requirement_type,
            "leg_index": self.leg_index,
            "mode": self.mode,
            "from_lat": self.from_lat,
            "from_lon": self.from_lon,
            "to_lat": self.to_lat,
            "to_lon": self.to_lon,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class JourneyLeg:
    index: int
    mode: MobilityMode
    from_node_id: str
    to_node_id: str
    edge_id: str
    edge_kind: EdgeKind
    from_ref: Optional[str] = None  # stop/station id when applicable
    to_ref: Optional[str] = None
    # Display names from GraphNode when known (Phase 7G steps).
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    route_id: Optional[str] = None
    provider: Optional[str] = None
    distance_meters: Optional[float] = None
    is_transfer: bool = False
    needs_enrichment: bool = False
    estimated_departure: Optional[str] = None
    estimated_arrival: Optional[str] = None
    waiting_seconds: Optional[int] = None
    segment_role: SegmentRole = SegmentRole.OTHER
    cost_inr: Optional[float] = None
    cost_status: str = ValueStatus.UNKNOWN.value
    duration_seconds: Optional[float] = None
    duration_status: str = ValueStatus.UNKNOWN.value
    walking_meters: float = 0.0
    provenance: Optional[DataProvenance] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "mode": self.mode.value,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "edge_id": self.edge_id,
            "edge_kind": self.edge_kind.value,
            "from_ref": self.from_ref,
            "to_ref": self.to_ref,
            "from_name": self.from_name,
            "to_name": self.to_name,
            "route_id": self.route_id,
            "provider": self.provider,
            "distance_meters": self.distance_meters,
            "is_transfer": self.is_transfer,
            "needs_enrichment": self.needs_enrichment,
            "estimated_departure": self.estimated_departure,
            "estimated_arrival": self.estimated_arrival,
            "waiting_seconds": self.waiting_seconds,
            "segment_role": self.segment_role.value,
            "cost_inr": self.cost_inr,
            "cost_status": self.cost_status,
            "duration_seconds": self.duration_seconds,
            "duration_status": self.duration_status,
            "walking_meters": self.walking_meters,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "metadata": dict(self.metadata),
        }


@dataclass
class Journey:
    candidate_id: str
    origin: Tuple[float, float]
    destination: Tuple[float, float]
    legs: List[JourneyLeg]
    transfer_count: int
    walking_distance_meters: float
    transit_leg_count: int
    road_leg_count: int
    modes: List[str]
    snapshot_versions: Dict[str, str]
    provenance_sources: List[str]
    enrichment_requirements: List[EnrichmentRequirement] = field(default_factory=list)
    temporal_feasibility: str = "unknown"  # known | unknown | infeasible
    warnings: List[str] = field(default_factory=list)
    # Phase 6D journey-level aggregates (scoring still Decision Engine).
    total_cost_inr: Optional[float] = None
    cost_status: str = ValueStatus.UNKNOWN.value
    total_duration_seconds: Optional[float] = None
    duration_status: str = ValueStatus.UNKNOWN.value
    access_walking_meters: float = 0.0
    transfer_walking_meters: float = 0.0
    egress_walking_meters: float = 0.0
    mode_signature: str = ""

    def to_dict(
        self,
        *,
        origin_label: Optional[str] = None,
        destination_label: Optional[str] = None,
        name_lookup: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        from src.journey_builder.steps import build_journey_steps, steps_to_dicts

        return {
            "candidate_id": self.candidate_id,
            "origin": list(self.origin),
            "destination": list(self.destination),
            "legs": [leg.to_dict() for leg in self.legs],
            "steps": steps_to_dicts(
                build_journey_steps(
                    self,
                    origin_label=origin_label,
                    destination_label=destination_label,
                    name_lookup=name_lookup,
                )
            ),
            "transfer_count": self.transfer_count,
            "walking_distance_meters": self.walking_distance_meters,
            "access_walking_meters": self.access_walking_meters,
            "transfer_walking_meters": self.transfer_walking_meters,
            "egress_walking_meters": self.egress_walking_meters,
            "transit_leg_count": self.transit_leg_count,
            "road_leg_count": self.road_leg_count,
            "modes": list(self.modes),
            "mode_signature": self.mode_signature,
            "snapshot_versions": dict(self.snapshot_versions),
            "provenance_sources": list(self.provenance_sources),
            "enrichment_requirements": [
                e.to_dict() for e in self.enrichment_requirements
            ],
            "temporal_feasibility": self.temporal_feasibility,
            "total_cost_inr": self.total_cost_inr,
            "cost_status": self.cost_status,
            "total_duration_seconds": self.total_duration_seconds,
            "duration_status": self.duration_status,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class JourneyBuildRequest:
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    departure_time: datetime
    constraints: Any = None  # JourneyConstraints — typed in constraints.py
    search_limits: Any = None  # SearchLimits

    @property
    def origin(self) -> Tuple[float, float]:
        return (self.origin_lat, self.origin_lon)

    @property
    def destination(self) -> Tuple[float, float]:
        return (self.destination_lat, self.destination_lon)


@dataclass
class JourneyBuildResult:
    candidates: List[Journey]
    search_metadata: Dict[str, Any]
    constraints_applied: Dict[str, Any]
    network_snapshot_versions: Dict[str, str]
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "search_metadata": dict(self.search_metadata),
            "constraints_applied": dict(self.constraints_applied),
            "network_snapshot_versions": dict(self.network_snapshot_versions),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }
