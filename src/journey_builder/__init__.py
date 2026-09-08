"""
Deterministic multimodal Journey Builder (Phase 5C).

Composes candidate journeys from StaticMobilityDataRepository topology.
Does NOT hardcode journey templates, call live Maps APIs, or rank journeys.
"""

from src.journey_builder.builder import DynamicJourneyBuilder
from src.journey_builder.constraints import JourneyConstraints, SearchLimits
from src.journey_builder.graph import MobilityNetworkGraph, build_mobility_graph
from src.journey_builder.models import (
    EnrichmentRequirement,
    GraphEdge,
    GraphNode,
    Journey,
    JourneyBuildRequest,
    JourneyBuildResult,
    JourneyLeg,
    NodeKind,
    EdgeKind,
    SegmentRole,
    ValueStatus,
)

__all__ = [
    "DynamicJourneyBuilder",
    "JourneyConstraints",
    "SearchLimits",
    "MobilityNetworkGraph",
    "build_mobility_graph",
    "EnrichmentRequirement",
    "GraphEdge",
    "GraphNode",
    "Journey",
    "JourneyBuildRequest",
    "JourneyBuildResult",
    "JourneyLeg",
    "NodeKind",
    "EdgeKind",
    "SegmentRole",
    "ValueStatus",
]
