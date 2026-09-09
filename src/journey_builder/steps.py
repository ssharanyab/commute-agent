"""
Phase 7G — Deterministic grounded journey steps + transfer points.

Derives user-facing instructions from already-built Journey legs.
Does not invent locations, call Gemini, or change ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from src.journey_builder.models import EdgeKind, Journey, JourneyLeg, SegmentRole
from src.network.models import MobilityMode


class JourneyStepType(str, Enum):
    LEG = "LEG"
    TRANSFER = "TRANSFER"


_PRIMARY_TRANSPORT = frozenset(
    {
        "bus",
        "metro",
        "auto",
        "cab",
    }
)

_WALK_FAMILY = frozenset({"walk", "walking"})


def _mode_token(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, Enum):
        raw = getattr(raw, "value", raw)
    token = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "walking": "walk",
        "auto_rickshaw": "auto",
        "rickshaw": "auto",
        "tuk_tuk": "auto",
        "bmtc": "bus",
        "bmrcl": "metro",
        "taxi": "cab",
        "drive": "cab",
        "rideshare": "cab",
        "uber": "cab",
        "ola": "cab",
    }
    return aliases.get(token, token)


def display_mode_label(mode: Any) -> str:
    token = _mode_token(mode)
    labels = {
        "walk": "Walk",
        "bus": "Bus",
        "metro": "Metro",
        "auto": "Auto",
        "cab": "Cab",
    }
    return labels.get(token, token.title() if token else "Route")


def _looks_like_raw_id(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    lower = t.lower()
    if lower.startswith(("stop:", "station:", "access:", "node:", "edge:")):
        return True
    if t.isdigit():
        return True
    if len(t) >= 8 and all(c.isalnum() or c in "_-" for c in t) and "_" in t:
        # e.g. electronic_city style ids without spaces — still usable if humanized
        pass
    if lower in {"unknown", "n/a", "null", "none", "undefined"}:
        return True
    return False


def humanize_place_name(raw: Optional[str]) -> Optional[str]:
    """Turn a known name into display text; never invent; never expose raw IDs."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or _looks_like_raw_id(text):
        return None
    # Underscore labels from network seeds → title case words.
    if "_" in text and " " not in text:
        text = text.replace("_", " ")
    # Collapse whitespace
    text = " ".join(text.split())
    if not text:
        return None
    # Already mixed-case place names kept; all-lower title-cased.
    if text.islower() or text.isupper():
        text = text.title()
    # Drop redundant "Bmtc"/"Bmrcl" noise tokens if alone.
    if text.lower() in {"bmtc", "bmrcl"}:
        return None
    return text


def resolve_node_display_name(
    *,
    explicit_name: Optional[str] = None,
    node_id: Optional[str] = None,
    source_ref: Optional[str] = None,
    name_lookup: Optional[Mapping[str, str]] = None,
    origin_label: Optional[str] = None,
    destination_label: Optional[str] = None,
    role_hint: Optional[str] = None,
) -> Optional[str]:
    """Resolve a safe display name from known data only."""
    lookup = name_lookup or {}

    # Access endpoints.
    nid = (node_id or "").strip().lower()
    is_origin_access = nid in {"access:origin", "origin"} or nid.endswith(":origin")
    is_dest_access = (
        nid in {"access:destination", "destination"} or nid.endswith(":destination")
    )
    if is_origin_access:
        return humanize_place_name(origin_label) or "Origin"
    if is_dest_access:
        return humanize_place_name(destination_label) or "Destination"

    name = humanize_place_name(explicit_name)
    if name:
        return name

    if source_ref and source_ref in lookup:
        name = humanize_place_name(lookup[source_ref])
        if name:
            return name

    if node_id and node_id in lookup:
        name = humanize_place_name(lookup[node_id])
        if name:
            return name

    # Strip stop:/station: prefixes only when remaining part is a real name in lookup.
    for prefix in ("stop:", "station:"):
        if nid.startswith(prefix):
            ref = node_id[len(prefix) :] if node_id else ""
            if ref in lookup:
                name = humanize_place_name(lookup[ref])
                if name:
                    return name
            # Do not use the raw id string as a name.
            break

    # Origin/destination labels only when the node is an access endpoint
    # (already handled) or when role_hint applies to unlabeled access-style legs.
    if role_hint == "origin" and is_origin_access:
        return humanize_place_name(origin_label) or "Origin"
    if role_hint == "destination" and is_dest_access:
        return humanize_place_name(destination_label) or "Destination"
    return None


@dataclass(frozen=True)
class JourneyStep:
    type: str  # LEG | TRANSFER
    instruction: str
    mode: Optional[str] = None
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    from_node_id: Optional[str] = None
    to_node_id: Optional[str] = None
    from_mode: Optional[str] = None
    to_mode: Optional[str] = None
    location_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "instruction": self.instruction,
            "mode": self.mode,
            "from_name": self.from_name,
            "to_name": self.to_name,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "location_name": self.location_name,
        }


def _leg_from_name(
    leg: JourneyLeg,
    *,
    name_lookup: Optional[Mapping[str, str]],
    origin_label: Optional[str],
    destination_label: Optional[str],
    is_first: bool,
) -> Optional[str]:
    explicit = getattr(leg, "from_name", None) or (leg.metadata or {}).get("from_name")
    return resolve_node_display_name(
        explicit_name=explicit if isinstance(explicit, str) else None,
        node_id=leg.from_node_id,
        source_ref=leg.from_ref,
        name_lookup=name_lookup,
        origin_label=origin_label,
        destination_label=destination_label,
        role_hint="origin" if is_first else None,
    )


def _leg_to_name(
    leg: JourneyLeg,
    *,
    name_lookup: Optional[Mapping[str, str]],
    origin_label: Optional[str],
    destination_label: Optional[str],
    is_last: bool,
) -> Optional[str]:
    explicit = getattr(leg, "to_name", None) or (leg.metadata or {}).get("to_name")
    return resolve_node_display_name(
        explicit_name=explicit if isinstance(explicit, str) else None,
        node_id=leg.to_node_id,
        source_ref=leg.to_ref,
        name_lookup=name_lookup,
        origin_label=origin_label,
        destination_label=destination_label,
        role_hint="destination" if is_last else None,
    )


def _is_walk_leg(leg: JourneyLeg) -> bool:
    token = _mode_token(leg.mode)
    if token in _WALK_FAMILY:
        return True
    kind = leg.edge_kind
    if isinstance(kind, Enum):
        kind = kind.value
    return str(kind) in {
        EdgeKind.WALK.value,
        EdgeKind.TRANSFER_WALK.value,
        EdgeKind.INTERCHANGE.value,
    }


def _is_primary_leg(leg: JourneyLeg) -> bool:
    return _mode_token(leg.mode) in _PRIMARY_TRANSPORT and not _is_walk_leg(leg)


def _leg_instruction(
    *,
    mode: str,
    from_name: Optional[str],
    to_name: Optional[str],
    is_first: bool,
    is_last: bool,
    segment_role: Any,
) -> str:
    label = display_mode_label(mode)
    role = segment_role.value if isinstance(segment_role, Enum) else str(segment_role or "")

    if mode == "walk":
        if is_last or role == SegmentRole.EGRESS.value:
            if to_name and to_name not in {"Destination", "Origin"}:
                return f"Walk to {to_name}"
            return "Walk to your destination"
        if to_name:
            return f"Walk to {to_name}"
        return "Continue on foot"

    if mode == "bus":
        if to_name:
            return f"Take the bus to {to_name}"
        return "Continue by Bus"
    if mode == "metro":
        if to_name:
            return f"Take the Metro to {to_name}"
        return "Continue by Metro"
    if mode == "auto":
        if to_name and not (is_last or role == SegmentRole.EGRESS.value):
            return f"Take an auto to {to_name}"
        if is_last or role in {
            SegmentRole.EGRESS.value,
            SegmentRole.FULL_JOURNEY_ROAD.value,
        }:
            return "Auto to destination" if not to_name or to_name == "Destination" else f"Take an auto to {to_name}"
        return "Continue by Auto"
    if mode == "cab":
        if is_last or role in {
            SegmentRole.EGRESS.value,
            SegmentRole.FULL_JOURNEY_ROAD.value,
        }:
            if to_name and to_name != "Destination":
                return f"Cab to {to_name}"
            return "Cab to destination"
        if to_name:
            return f"Take a cab to {to_name}"
        return "Continue by Cab"

    if to_name:
        return f"Continue by {label} to {to_name}"
    return f"Continue by {label}"


def _transfer_instruction(
    *,
    from_mode: str,
    to_mode: str,
    location_name: Optional[str],
) -> str:
    from_label = display_mode_label(from_mode)
    to_label = display_mode_label(to_mode)
    if from_mode == "bus" and to_mode == "bus":
        if location_name:
            return f"Change buses at {location_name}"
        return "Change buses"
    if location_name:
        return f"Change from {from_label} to {to_label} at {location_name}"
    return f"Change from {from_label} to {to_label}"


def _should_emit_transfer(prev: JourneyLeg, nxt: JourneyLeg) -> bool:
    """Meaningful service/mode change between two primary transport legs."""
    if not _is_primary_leg(prev) or not _is_primary_leg(nxt):
        return False
    prev_m = _mode_token(prev.mode)
    next_m = _mode_token(nxt.mode)
    if prev_m != next_m:
        return True
    # Same mode (e.g. bus→bus): only when journey marks a real transfer/service change.
    if prev_m == "bus" and (
        bool(nxt.is_transfer)
        or (
            prev.route_id
            and nxt.route_id
            and prev.route_id != nxt.route_id
        )
    ):
        return True
    if prev_m == "metro" and bool(nxt.is_transfer):
        return True
    return False


def build_journey_steps(
    journey: Union[Journey, Sequence[JourneyLeg]],
    *,
    origin_label: Optional[str] = None,
    destination_label: Optional[str] = None,
    name_lookup: Optional[Mapping[str, str]] = None,
) -> List[JourneyStep]:
    """
    Build ordered LEG / TRANSFER steps from a journey.

    Transfer steps appear between primary transport legs (bus/metro/auto/cab),
    not for walk access/egress connectors.
    """
    if isinstance(journey, Journey):
        legs: Sequence[JourneyLeg] = journey.legs
    else:
        legs = journey
    if not legs:
        return []

    steps: List[JourneyStep] = []
    prev_primary: Optional[JourneyLeg] = None
    prev_primary_arrival: Optional[str] = None
    n = len(legs)

    for idx, leg in enumerate(legs):
        is_first = idx == 0
        is_last = idx == n - 1
        mode = _mode_token(leg.mode) or "walk"
        from_name = _leg_from_name(
            leg,
            name_lookup=name_lookup,
            origin_label=origin_label,
            destination_label=destination_label,
            is_first=is_first,
        )
        to_name = _leg_to_name(
            leg,
            name_lookup=name_lookup,
            origin_label=origin_label,
            destination_label=destination_label,
            is_last=is_last,
        )

        if _is_primary_leg(leg) and prev_primary is not None:
            if _should_emit_transfer(prev_primary, leg):
                location = prev_primary_arrival or from_name
                steps.append(
                    JourneyStep(
                        type=JourneyStepType.TRANSFER.value,
                        instruction=_transfer_instruction(
                            from_mode=_mode_token(prev_primary.mode),
                            to_mode=mode,
                            location_name=location,
                        ),
                        from_mode=_mode_token(prev_primary.mode),
                        to_mode=mode,
                        location_name=location,
                        from_node_id=prev_primary.to_node_id,
                        to_node_id=leg.from_node_id,
                    )
                )

        steps.append(
            JourneyStep(
                type=JourneyStepType.LEG.value,
                mode=mode,
                from_name=from_name,
                to_name=to_name,
                from_node_id=leg.from_node_id,
                to_node_id=leg.to_node_id,
                instruction=_leg_instruction(
                    mode=mode,
                    from_name=from_name,
                    to_name=to_name,
                    is_first=is_first,
                    is_last=is_last,
                    segment_role=leg.segment_role,
                ),
            )
        )

        if _is_primary_leg(leg):
            prev_primary = leg
            prev_primary_arrival = to_name

    return steps


def steps_to_dicts(steps: Iterable[JourneyStep]) -> List[Dict[str, Any]]:
    return [s.to_dict() for s in steps]


def attach_steps_to_top_selection(
    top_selection: Optional[Dict[str, Any]],
    journeys: Sequence[Journey],
    *,
    origin_label: Optional[str] = None,
    destination_label: Optional[str] = None,
    name_lookup: Optional[Mapping[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Attach ``steps`` to each TopJourneyOption dict using matching journeys."""
    if not top_selection:
        return top_selection
    by_id = {j.candidate_id: j for j in journeys}

    def enrich_option(raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        opt = dict(raw)
        cid = opt.get("candidate_id") or opt.get("route_id")
        journey = by_id.get(cid) if cid else None
        if journey is not None:
            opt["steps"] = steps_to_dicts(
                build_journey_steps(
                    journey,
                    origin_label=origin_label,
                    destination_label=destination_label,
                    name_lookup=name_lookup,
                )
            )
        else:
            opt.setdefault("steps", [])
        return opt

    out = dict(top_selection)
    if out.get("recommended") is not None:
        out["recommended"] = enrich_option(out["recommended"])
    out["alternatives"] = [
        enrich_option(a) for a in (out.get("alternatives") or [])
    ]
    out["top_journeys"] = [
        enrich_option(a) for a in (out.get("top_journeys") or [])
    ]
    return out
