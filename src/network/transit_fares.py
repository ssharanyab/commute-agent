"""
Transit fare lookup (Phase 7K-2 / 7K-6).

BMRCL token fares: official station-count slabs (Revised Fare Chart 14.02.2025).
Unknown remains unknown (never ₹0). No LLM / fuzzy / OD hardcoding.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.journey_builder.models import ValueStatus
from src.network.models import MobilityMode

_DEFAULT_BMRCL_FARE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "mobility_network"
    / "bmrcl"
    / "fares"
    / "bmrcl_token_fare_slabs_v20250214.json"
)


@lru_cache(maxsize=1)
def load_default_bmrcl_token_fare_rules() -> Tuple[Dict[str, Any], ...]:
    """Load versioned official BMRCL token fare artifact (immutable tuple)."""
    path = _DEFAULT_BMRCL_FARE_PATH
    if not path.exists():
        return tuple()
    doc = json.loads(path.read_text(encoding="utf-8"))
    rules = doc.get("fare_rules") or []
    return tuple(dict(r) for r in rules if isinstance(r, dict))


def _as_rule_dict(rule: Any) -> Optional[Dict[str, Any]]:
    if rule is None:
        return None
    if hasattr(rule, "to_dict"):
        return rule.to_dict()
    if isinstance(rule, dict):
        return rule
    return None


def _is_bmrcl_station_slab_rule(rule: Dict[str, Any]) -> bool:
    if str(rule.get("provider") or "").upper() != "BMRCL":
        return False
    mode = rule.get("mode")
    mode_s = mode.value if hasattr(mode, "value") else str(mode or "")
    if mode_s != MobilityMode.METRO.value:
        return False
    structure = rule.get("rule_structure") or {}
    return structure.get("fare_kind") == "token_station_count_slabs"


def select_bmrcl_token_fare_rule(
    fare_rules: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Prefer published snapshot rules; fall back to versioned official artifact."""
    for raw in list(fare_rules or []):
        rule = _as_rule_dict(raw)
        if rule and _is_bmrcl_station_slab_rule(rule):
            return rule
    for raw in load_default_bmrcl_token_fare_rules():
        if _is_bmrcl_station_slab_rule(raw):
            return dict(raw)
    return None


def fare_for_stations_travelled(
    stations_travelled: int,
    *,
    rule: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[float], str, Dict[str, Any]]:
    """
    Map stations travelled (excluding origin) to token fare.

    stations_travelled == 0 → same-station entry/exit fare.
    """
    meta: Dict[str, Any] = {
        "fare_kind": "bmrcl_token_station_count_slabs",
        "stations_travelled_excluding_origin": stations_travelled,
    }
    if rule is None:
        rule = select_bmrcl_token_fare_rule()
    if rule is None:
        meta["note"] = "No authoritative BMRCL token fare rule loaded"
        return None, ValueStatus.UNKNOWN.value, meta

    structure = dict(rule.get("rule_structure") or {})
    meta.update(
        {
            "rule_id": rule.get("id"),
            "rule_version": rule.get("version"),
            "provenance_source": (rule.get("provenance") or {}).get("source")
            or rule.get("source"),
            "provenance_source_url": (rule.get("provenance") or {}).get("source_url")
            or rule.get("source_url"),
            "effective_from": rule.get("effective_from"),
        }
    )

    if stations_travelled < 0:
        meta["note"] = "invalid_stations_travelled"
        return None, ValueStatus.UNKNOWN.value, meta

    if stations_travelled == 0:
        amount = float(structure.get("same_station_entry_exit_inr", 10))
        meta["slab"] = 0
        meta["same_station"] = True
        return amount, ValueStatus.KNOWN.value, meta

    for slab in structure.get("slabs") or []:
        lo = int(slab["min_stations"])
        hi = slab.get("max_stations")
        if stations_travelled < lo:
            continue
        if hi is None or stations_travelled <= int(hi):
            amount = float(slab["fare_inr"])
            meta["slab"] = slab.get("slab")
            meta["slab_min_stations"] = lo
            meta["slab_max_stations"] = hi
            return amount, ValueStatus.KNOWN.value, meta

    meta["note"] = "stations_travelled_outside_published_slabs"
    return None, ValueStatus.UNKNOWN.value, meta


def lookup_transit_fare_inr(
    *,
    mode: MobilityMode,
    from_station_id: Optional[str],
    to_station_id: Optional[str],
    route_id: Optional[str] = None,
    fare_rules: Optional[list] = None,
    stations_travelled: Optional[int] = None,
) -> Tuple[Optional[float], str, Dict[str, Any]]:
    """
    Resolve a transit fare from published / official fare_rules when present.

    Returns (amount_inr_or_None, cost_status, meta). Unknown ≠ ₹0.
    """
    meta: Dict[str, Any] = {
        "fare_kind": "transit_fare_lookup",
        "mode": mode.value if isinstance(mode, MobilityMode) else str(mode),
        "from_station_id": from_station_id,
        "to_station_id": to_station_id,
        "route_id": route_id,
        "stations_travelled": stations_travelled,
    }

    if mode != MobilityMode.METRO:
        meta.update(
            {
                "fare_kind": "transit_fare_not_configured_for_mode",
                "note": "Only BMRCL metro token slabs are configured; other transit stays unknown.",
            }
        )
        return None, ValueStatus.UNKNOWN.value, meta

    if from_station_id and to_station_id and from_station_id == to_station_id:
        stations_travelled = 0
    elif stations_travelled is None:
        meta.update(
            {
                "fare_kind": "bmrcl_stations_travelled_unknown",
                "note": (
                    "Metro fare requires stations_travelled from network path "
                    "(excluding origin). No fabrication from distance."
                ),
            }
        )
        return None, ValueStatus.UNKNOWN.value, meta

    rule = select_bmrcl_token_fare_rule(fare_rules)
    if rule is None:
        meta.update(
            {
                "fare_kind": "transit_fare_not_in_published_snapshot",
                "note": (
                    "No authoritative BMRCL token fare rule available. "
                    "Do not invent fares."
                ),
            }
        )
        return None, ValueStatus.UNKNOWN.value, meta

    amount, status, fare_meta = fare_for_stations_travelled(
        int(stations_travelled), rule=rule
    )
    meta.update(fare_meta)
    return amount, status, meta
