"""
Search limits and hard constraints for the Journey Builder.

Soft preference scoring remains the Decision Engine's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from src.decision_engine.scoring import (
    expand_excluded_mode_tokens,
    mode_is_excluded,
)
from src.network.models import MobilityMode


@dataclass(frozen=True)
class SearchLimits:
    """Algorithmic safety bounds — not journey templates."""

    max_walking_access_meters: float = 800.0
    max_walking_egress_meters: float = 800.0
    max_walk_transfer_meters: float = 400.0
    max_direct_walk_meters: float = 2000.0
    max_road_access_meters: float = 5000.0
    # Full OD road (cab/auto) — geographic cap before enrichment; not a fare claim.
    max_direct_road_meters: float = 80000.0
    max_transfers: int = 3
    max_legs: int = 8
    max_candidates: int = 20
    max_nodes_explored: int = 5000
    allow_road_access: bool = True
    allow_direct_road: bool = True
    road_access_modes: tuple = (
        MobilityMode.AUTO_RICKSHAW.value,
        MobilityMode.CAB.value,
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_walking_access_meters": self.max_walking_access_meters,
            "max_walking_egress_meters": self.max_walking_egress_meters,
            "max_walk_transfer_meters": self.max_walk_transfer_meters,
            "max_direct_walk_meters": self.max_direct_walk_meters,
            "max_road_access_meters": self.max_road_access_meters,
            "max_direct_road_meters": self.max_direct_road_meters,
            "max_transfers": self.max_transfers,
            "max_legs": self.max_legs,
            "max_candidates": self.max_candidates,
            "max_nodes_explored": self.max_nodes_explored,
            "allow_road_access": self.allow_road_access,
            "allow_direct_road": self.allow_direct_road,
            "road_access_modes": list(self.road_access_modes),
        }


@dataclass(frozen=True)
class JourneyConstraints:
    """Hard constraints applied during search (defense-in-depth with evaluator)."""

    excluded_modes: Optional[List[str]] = None
    max_walking_meters: Optional[float] = None

    def expanded_excluded(self) -> Set[str]:
        # Align with Decision Engine: cab family does NOT include auto_rickshaw.
        return set(expand_excluded_mode_tokens(self.excluded_modes))

    def mode_allowed(self, mode: str | MobilityMode) -> bool:
        token = mode.value if isinstance(mode, MobilityMode) else str(mode)
        token = token.strip().lower()
        if token in self.expanded_excluded():
            return False
        return not mode_is_excluded(token, self.excluded_modes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "excluded_modes": list(self.excluded_modes)
            if self.excluded_modes
            else None,
            "max_walking_meters": self.max_walking_meters,
            "expanded_excluded": sorted(self.expanded_excluded()),
        }
