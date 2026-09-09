"""
Phase 7B — Strategy-aware eligibility and hard constraint checks.

Lexicographic strategy tiers sit *above* existing preference scoring:
hard constraints → strategy eligibility / tier → Decision Engine scores.
No arbitrary score bonuses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agent.mobility_strategy import (
    AccessoryMode,
    MobilityConstraints,
    MobilityStrategy,
    is_public_transport_mode,
)
from src.decision_engine.models import RouteCandidate
from src.decision_engine.scoring import mode_is_excluded


class BackboneKind(str, Enum):
    PUBLIC_TRANSPORT = "public_transport"
    ROAD = "road"
    WALK = "walk"
    MIXED = "mixed"
    UNKNOWN = "unknown"


_WALK_FAMILY: Set[str] = {"walk", "walking"}


def _norm(mode: Any) -> str:
    if mode is None:
        return ""
    if isinstance(mode, Enum):
        return str(getattr(mode, "value", mode)).strip().lower()
    return str(mode).strip().lower()


def candidate_mode_tokens(candidate: RouteCandidate) -> List[str]:
    """Modes present on the complete journey (component_modes + top-level)."""
    tokens: List[str] = []
    seen: Set[str] = set()
    for raw in list(candidate.component_modes or []) + [candidate.mode]:
        token = _norm(raw)
        if not token or token in {"hybrid", "unknown", "mixed"}:
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def is_road_mode(mode: Any) -> bool:
    token = _norm(mode)
    if not token:
        return False
    return mode_is_excluded(token, ["cab"]) or mode_is_excluded(token, ["auto"])


def is_walk_mode(mode: Any) -> bool:
    return _norm(mode) in _WALK_FAMILY


def is_accessory_mode(mode: Any) -> bool:
    """Walk / auto / cab — modes that can serve as access/egress."""
    return is_walk_mode(mode) or is_road_mode(mode)


def accessory_family_token(mode: Any) -> Optional[str]:
    """Map a mode to AccessoryMode wire value, or None if not an accessory."""
    token = _norm(mode)
    if token in _WALK_FAMILY:
        return AccessoryMode.WALK.value
    if mode_is_excluded(token, ["auto"]):
        return AccessoryMode.AUTO.value
    if mode_is_excluded(token, ["cab"]):
        return AccessoryMode.CAB.value
    return None


def classify_backbone(candidate: RouteCandidate) -> BackboneKind:
    """Classify the complete journey backbone from canonical modes."""
    tokens = candidate_mode_tokens(candidate)
    if not tokens:
        return BackboneKind.UNKNOWN
    has_pt = any(is_public_transport_mode(t) for t in tokens)
    has_road = any(is_road_mode(t) for t in tokens)
    has_walk = any(is_walk_mode(t) for t in tokens)
    if has_pt:
        return BackboneKind.PUBLIC_TRANSPORT
    if has_road:
        return BackboneKind.ROAD
    if has_walk and not has_road and not has_pt:
        return BackboneKind.WALK
    return BackboneKind.MIXED


def has_public_transport_backbone(candidate: RouteCandidate) -> bool:
    return classify_backbone(candidate) == BackboneKind.PUBLIC_TRANSPORT


def has_road_transport_backbone(candidate: RouteCandidate) -> bool:
    """Road-primary journey (no public-transport legs)."""
    return classify_backbone(candidate) == BackboneKind.ROAD


def total_walking_meters(
    candidate: RouteCandidate,
) -> Tuple[Optional[float], str]:
    """
    Aggregate walking distance for the complete journey.

    Returns (meters, status) where status is known | unknown.
    Does not invent distance from preference minutes alone when meters missing.
    """
    explicit = getattr(candidate, "walking_distance_meters", None)
    if explicit is not None:
        return float(explicit), "known"

    parts = [
        candidate.access_walking_meters,
        candidate.transfer_walking_meters,
        candidate.egress_walking_meters,
    ]
    if any(p is not None for p in parts):
        return float(sum(float(p or 0.0) for p in parts)), "known"

    # No meter fields — cannot verify a meters-based hard constraint.
    if candidate.walking_minutes and candidate.walking_minutes > 0:
        return None, "unknown"
    return 0.0, "known"


def validate_mobility_constraints(
    candidate: RouteCandidate,
    *,
    strategy: Optional[MobilityStrategy],
    constraints: Optional[MobilityConstraints],
) -> List[str]:
    """Hard constraint + hard strategy violations (empty ⇒ eligible)."""
    violations: List[str] = []
    tokens = candidate_mode_tokens(candidate)

    # --- PUBLIC_TRANSPORT_ONLY (hard strategy) ---
    if strategy == MobilityStrategy.PUBLIC_TRANSPORT_ONLY:
        for token in tokens:
            if is_road_mode(token):
                violations.append(
                    f"STRATEGY_PUBLIC_TRANSPORT_ONLY (road mode {token} not allowed)"
                )
                break
            if not (
                is_public_transport_mode(token)
                or is_walk_mode(token)
            ):
                # Unknown non-PT, non-walk mode — reject safely.
                if token and not is_accessory_mode(token):
                    violations.append(
                        f"STRATEGY_PUBLIC_TRANSPORT_ONLY (mode {token} not allowed)"
                    )
                    break

    if constraints is None:
        return violations

    # --- excluded_modes (also applied via UserPreferences; keep explicit here
    # when only present on MobilityConstraints) ---
    if constraints.excluded_modes:
        for token in tokens:
            if mode_is_excluded(token, constraints.excluded_modes):
                violations.append(
                    f"EXCLUDED_MODE ({token} excluded by user constraint)"
                )
                break

    # --- max_transfers ---
    if constraints.max_transfers is not None:
        if int(candidate.transfers) > int(constraints.max_transfers):
            violations.append(
                f"EXCEEDS_MAX_TRANSFERS ({candidate.transfers} > {constraints.max_transfers})"
            )

    # --- max_walking_distance_meters ---
    if constraints.max_walking_distance_meters is not None:
        meters, status = total_walking_meters(candidate)
        limit = float(constraints.max_walking_distance_meters)
        if status == "unknown" or meters is None:
            violations.append(
                "UNKNOWN_WALKING_DISTANCE (cannot verify max_walking_distance_meters)"
            )
        elif meters > limit:
            violations.append(
                f"EXCEEDS_MAX_WALKING_DISTANCE ({meters:.0f} m > {limit:.0f} m)"
            )

    # --- allowed_accessory_modes (allow-list when explicitly set) ---
    if constraints.allowed_accessory_modes is not None:
        allowed = {m.value for m in constraints.allowed_accessory_modes}
        backbone = classify_backbone(candidate)
        if backbone == BackboneKind.PUBLIC_TRANSPORT:
            # Non-PT modes are accessories / connectors.
            for token in tokens:
                if is_public_transport_mode(token):
                    continue
                family = accessory_family_token(token)
                if family is None:
                    violations.append(
                        f"ACCESSORY_MODE_NOT_ALLOWED ({token})"
                    )
                    break
                if family not in allowed:
                    violations.append(
                        f"ACCESSORY_MODE_NOT_ALLOWED ({family})"
                    )
                    break
        elif backbone == BackboneKind.ROAD:
            # Road is backbone; only additional walk (or secondary road) checked.
            road_tokens = [t for t in tokens if is_road_mode(t)]
            primary_road = road_tokens[0] if road_tokens else None
            for token in tokens:
                if is_road_mode(token) and _norm(token) == _norm(primary_road):
                    continue
                if is_road_mode(token) and primary_road is not None:
                    # Multiple distinct road modes (e.g. auto→cab) — treat extras
                    # as accessories that must be allowed.
                    family = accessory_family_token(token)
                    if family is None or family not in allowed:
                        violations.append(
                            f"ACCESSORY_MODE_NOT_ALLOWED ({family or token})"
                        )
                        break
                    continue
                if is_walk_mode(token):
                    if AccessoryMode.WALK.value not in allowed:
                        violations.append("ACCESSORY_MODE_NOT_ALLOWED (walk)")
                        break
                elif is_public_transport_mode(token):
                    # Road-backbone tier shouldn't include PT; leave to strategy.
                    pass
                else:
                    family = accessory_family_token(token)
                    if family is not None and family not in allowed:
                        violations.append(
                            f"ACCESSORY_MODE_NOT_ALLOWED ({family})"
                        )
                        break

    return list(dict.fromkeys(violations))


def strategy_tier_key(
    candidate: RouteCandidate,
    strategy: Optional[MobilityStrategy],
) -> int:
    """
    Lower is better. Used for lexicographic ordering before preference scores.

    AGENT_DECIDES / unset → all tier 0.
    PUBLIC_TRANSPORT_FIRST → PT backbone 0, else 1.
    ROAD_TRANSPORT_FIRST → road backbone 0, else 1.
    PUBLIC_TRANSPORT_ONLY → already hard-filtered; all remaining tier 0.
    """
    if strategy is None or strategy == MobilityStrategy.AGENT_DECIDES:
        return 0
    if strategy == MobilityStrategy.PUBLIC_TRANSPORT_ONLY:
        return 0
    if strategy == MobilityStrategy.PUBLIC_TRANSPORT_FIRST:
        return 0 if has_public_transport_backbone(candidate) else 1
    if strategy == MobilityStrategy.ROAD_TRANSPORT_FIRST:
        return 0 if has_road_transport_backbone(candidate) else 1
    return 0


@dataclass
class StrategyEvaluationMeta:
    strategy_applied: Optional[str] = None
    backbone_by_route_id: Dict[str, str] = field(default_factory=dict)
    constraint_rejections: List[Dict[str, Any]] = field(default_factory=list)
    strategy_eligible_route_ids: List[str] = field(default_factory=list)
    strategy_tier_route_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_applied": self.strategy_applied,
            "backbone_by_route_id": dict(self.backbone_by_route_id),
            "constraint_rejections": list(self.constraint_rejections),
            "strategy_eligible_route_ids": list(self.strategy_eligible_route_ids),
            "strategy_tier_route_ids": list(self.strategy_tier_route_ids),
        }
