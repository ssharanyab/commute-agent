"""
Phase 7A — Mobility strategy + constraint contract.

Strategy answers "how should I travel?"; preference_profile answers
"what matters most within that strategy?". Neither is applied to ranking
in Phase 7A — values are carried for Phase 7B.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set

from src.network.models import MobilityMode


class MobilityStrategy(str, Enum):
    """User mobility strategy (journey composition intent)."""

    AGENT_DECIDES = "AGENT_DECIDES"
    PUBLIC_TRANSPORT_FIRST = "PUBLIC_TRANSPORT_FIRST"
    ROAD_TRANSPORT_FIRST = "ROAD_TRANSPORT_FIRST"
    PUBLIC_TRANSPORT_ONLY = "PUBLIC_TRANSPORT_ONLY"

    @classmethod
    def parse(cls, raw: Any) -> "MobilityStrategy":
        if isinstance(raw, cls):
            return raw
        text = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return cls(text)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in cls)
            raise ValueError(
                f"invalid mobility strategy {raw!r}; expected one of: {allowed}"
            ) from exc


class AccessoryMode(str, Enum):
    """Allowed first/last-mile / access accessory modes (permissions only)."""

    WALK = "walk"
    AUTO = "auto"
    CAB = "cab"

    @classmethod
    def parse(cls, raw: Any) -> "AccessoryMode":
        if isinstance(raw, cls):
            return raw
        token = str(raw or "").strip().lower().replace("-", "_")
        aliases = {
            "walk": cls.WALK,
            "walking": cls.WALK,
            "auto": cls.AUTO,
            "auto_rickshaw": cls.AUTO,
            "rickshaw": cls.AUTO,
            "tuk_tuk": cls.AUTO,
            "cab": cls.CAB,
            "taxi": cls.CAB,
            "drive": cls.CAB,
            "rideshare": cls.CAB,
        }
        if token not in aliases:
            allowed = ", ".join(m.value for m in cls)
            raise ValueError(
                f"invalid accessory mode {raw!r}; expected one of: {allowed}"
            )
        return aliases[token]


# Canonical public-transport modes for Bengaluru (BMTC bus + BMRCL metro).
# Uses MobilityMode values; network aliases (bmtc / bmrcl) are accepted for
# classification of journey mode tokens without inventing new enums.
_PUBLIC_TRANSPORT_CANONICAL = frozenset(
    {
        MobilityMode.BUS.value,  # BMTC
        MobilityMode.METRO.value,  # BMRCL
    }
)
_PUBLIC_TRANSPORT_ALIASES = frozenset(
    {
        "bmtc",
        "bmrcl",
        "bus",
        "metro",
        "transit",
        "public_transport",
    }
)


def public_transport_mode_values() -> frozenset:
    """Canonical public-transport MobilityMode wire values (bus, metro)."""
    return _PUBLIC_TRANSPORT_CANONICAL


def is_public_transport_mode(mode: Any) -> bool:
    """True when ``mode`` is BMTC/BMRCL (bus/metro) or a known alias."""
    if isinstance(mode, MobilityMode):
        token = mode.value
    elif isinstance(mode, Enum):
        token = str(getattr(mode, "value", mode)).strip().lower()
    else:
        token = str(mode or "").strip().lower()
    if token in {"auto_rickshaw"}:
        return False
    if token in _PUBLIC_TRANSPORT_CANONICAL or token in _PUBLIC_TRANSPORT_ALIASES:
        return True
    return False


def normalize_excluded_mode_token(raw: Any) -> str:
    """Normalize an exclusion token for storage (families expanded by Decision Engine)."""
    token = str(raw or "").strip().lower().replace("-", "_")
    if not token:
        raise ValueError("excluded mode must not be empty")
    aliases = {
        "taxi": "cab",
        "drive": "cab",
        "rideshare": "cab",
        "uber": "cab",
        "ola": "cab",
        "cabs": "cab",
        "taxis": "cab",
        "auto_rickshaw": "auto",
        "rickshaw": "auto",
        "tuk_tuk": "auto",
        "walking": "walk",
        "bmtc": "bus",
        "bmrcl": "metro",
    }
    return aliases.get(token, token)


@dataclass(frozen=True)
class MobilityConstraints:
    """Hard / soft-structure constraints for journey composition (Phase 7A contract).

    Absent fields mean "not specified" — callers must not invent defaults that
    change existing Phase 6F/6G behavior.
    """

    excluded_modes: Optional[List[str]] = None
    max_walking_distance_meters: Optional[float] = None
    max_transfers: Optional[int] = None
    allowed_accessory_modes: Optional[List[AccessoryMode]] = None

    def __post_init__(self) -> None:
        if self.max_walking_distance_meters is not None:
            if self.max_walking_distance_meters < 0:
                raise ValueError("max_walking_distance_meters must be >= 0")
        if self.max_transfers is not None:
            if self.max_transfers < 0:
                raise ValueError("max_transfers must be >= 0")

    @classmethod
    def from_mapping(cls, raw: Optional[Dict[str, Any]]) -> Optional["MobilityConstraints"]:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("constraints must be an object")
        excluded_raw = raw.get("excluded_modes")
        excluded: Optional[List[str]] = None
        if excluded_raw is not None:
            if not isinstance(excluded_raw, (list, tuple)):
                raise ValueError("excluded_modes must be a list")
            excluded = [normalize_excluded_mode_token(m) for m in excluded_raw]

        accessories_raw = raw.get("allowed_accessory_modes")
        accessories: Optional[List[AccessoryMode]] = None
        if accessories_raw is not None:
            if not isinstance(accessories_raw, (list, tuple)):
                raise ValueError("allowed_accessory_modes must be a list")
            accessories = [AccessoryMode.parse(m) for m in accessories_raw]

        max_walk = raw.get("max_walking_distance_meters")
        if max_walk is not None:
            max_walk = float(max_walk)

        max_xfer = raw.get("max_transfers")
        if max_xfer is not None:
            max_xfer = int(max_xfer)

        return cls(
            excluded_modes=excluded,
            max_walking_distance_meters=max_walk,
            max_transfers=max_xfer,
            allowed_accessory_modes=accessories,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "excluded_modes": list(self.excluded_modes)
            if self.excluded_modes is not None
            else None,
            "max_walking_distance_meters": self.max_walking_distance_meters,
            "max_transfers": self.max_transfers,
            "allowed_accessory_modes": [
                m.value for m in self.allowed_accessory_modes
            ]
            if self.allowed_accessory_modes is not None
            else None,
        }


def parse_strategy(raw: Any) -> Optional[MobilityStrategy]:
    """Parse optional strategy; ``None`` / blank → unset (backward compatible)."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    return MobilityStrategy.parse(raw)


def merge_excluded_modes(
    preferences_excluded: Optional[Sequence[str]],
    constraints: Optional[MobilityConstraints],
) -> Optional[List[str]]:
    """Union preferences.excluded_modes with constraints.excluded_modes (order-preserving)."""
    out: List[str] = []
    seen: Set[str] = set()
    for source in (
        preferences_excluded,
        None if constraints is None else constraints.excluded_modes,
    ):
        if not source:
            continue
        for raw in source:
            token = normalize_excluded_mode_token(raw)
            if token not in seen:
                seen.add(token)
                out.append(token)
    return out or None
