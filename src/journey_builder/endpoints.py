"""
Journey / plan endpoint semantics (Phase 7K-4).

A request endpoint is either a generic geographic place or an already-known
mobility network node (BMRCL station, BMTC stop, …).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class EndpointKind(str, Enum):
    PLACE = "place"
    NETWORK_NODE = "network_node"


class EndpointResolutionError(ValueError):
    """Invalid or unknown network_node identity — do not silent-fallback."""

    def __init__(self, message: str, *, code: str = "INVALID_ENDPOINT"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class JourneyEndpoint:
    """Smallest endpoint contract for plan + Journey Builder."""

    kind: EndpointKind
    lat: Optional[float] = None
    lon: Optional[float] = None
    network: Optional[str] = None  # bmrcl | bmtc | …
    node_id: Optional[str] = None  # station:… | stop:…
    place_id: Optional[str] = None
    display_name: Optional[str] = None

    @property
    def is_network_node(self) -> bool:
        return self.kind == EndpointKind.NETWORK_NODE

    @property
    def is_place(self) -> bool:
        return self.kind == EndpointKind.PLACE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "lat": self.lat,
            "lon": self.lon,
            "network": self.network,
            "node_id": self.node_id,
            "place_id": self.place_id,
            "display_name": self.display_name,
        }

    @classmethod
    def place(
        cls,
        *,
        lat: float,
        lon: float,
        place_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> "JourneyEndpoint":
        return cls(
            kind=EndpointKind.PLACE,
            lat=float(lat),
            lon=float(lon),
            place_id=place_id,
            display_name=display_name,
        )

    @classmethod
    def network_node(
        cls,
        *,
        network: str,
        node_id: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        place_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> "JourneyEndpoint":
        return cls(
            kind=EndpointKind.NETWORK_NODE,
            network=(network or "").strip().lower() or None,
            node_id=normalize_network_node_id(node_id, network=network),
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            place_id=place_id,
            display_name=display_name,
        )

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> Optional["JourneyEndpoint"]:
        if not raw:
            return None
        kind_raw = str(raw.get("kind") or EndpointKind.PLACE.value).strip().lower()
        try:
            kind = EndpointKind(kind_raw)
        except ValueError as exc:
            raise EndpointResolutionError(
                f"Unknown endpoint kind {kind_raw!r}",
                code="INVALID_ENDPOINT_KIND",
            ) from exc
        lat = raw.get("lat", raw.get("latitude"))
        lon = raw.get("lon", raw.get("longitude"))
        if kind == EndpointKind.NETWORK_NODE:
            network = str(raw.get("network") or "").strip().lower()
            node_id = raw.get("node_id") or raw.get("nodeId")
            if not network or not node_id:
                raise EndpointResolutionError(
                    "network_node requires network and node_id",
                    code="INVALID_NETWORK_NODE",
                )
            return cls.network_node(
                network=network,
                node_id=str(node_id),
                lat=float(lat) if lat is not None else None,
                lon=float(lon) if lon is not None else None,
                place_id=(str(raw["place_id"]) if raw.get("place_id") else None),
                display_name=(
                    str(raw["display_name"]) if raw.get("display_name") else None
                ),
            )
        if lat is None or lon is None:
            raise EndpointResolutionError(
                "place endpoint requires lat and lon",
                code="INVALID_PLACE_ENDPOINT",
            )
        return cls.place(
            lat=float(lat),
            lon=float(lon),
            place_id=(str(raw["place_id"]) if raw.get("place_id") else None),
            display_name=(
                str(raw["display_name"]) if raw.get("display_name") else None
            ),
        )


def normalize_network_node_id(node_id: str, *, network: Optional[str] = None) -> str:
    """Normalize to graph node id: station:… or stop:…."""
    raw = (node_id or "").strip()
    if not raw:
        raise EndpointResolutionError("empty node_id", code="INVALID_NETWORK_NODE")
    lower = raw.lower()
    if lower.startswith("station:") or lower.startswith("stop:"):
        prefix, _, rest = raw.partition(":")
        return f"{prefix.lower()}:{rest}"
    net = (network or "").strip().lower()
    if net == "bmrcl":
        return f"station:{raw}"
    if net == "bmtc":
        return f"stop:{raw}"
    # Ambiguous bare id without network prefix.
    raise EndpointResolutionError(
        f"node_id {node_id!r} must be 'station:…' or 'stop:…' "
        f"(or supply network=bmrcl|bmtc)",
        code="INVALID_NETWORK_NODE",
    )


def network_for_node_id(node_id: str) -> Optional[str]:
    if node_id.startswith("station:"):
        return "bmrcl"
    if node_id.startswith("stop:"):
        return "bmtc"
    return None


def coords_from_endpoint(
    endpoint: JourneyEndpoint,
) -> Tuple[Optional[float], Optional[float]]:
    if endpoint.lat is not None and endpoint.lon is not None:
        return float(endpoint.lat), float(endpoint.lon)
    return None, None
