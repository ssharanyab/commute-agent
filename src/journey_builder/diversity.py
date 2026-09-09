"""
Structural candidate diversity helpers (Phase 6D multimodal).

Signatures / structural keys are for retention and audit only —
never used as journey-generation templates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.journey_builder.models import Journey, JourneyLeg


def _normalize_mode_token(raw: str) -> str:
    token = str(raw).strip().lower()
    if token == "auto_rickshaw":
        return "auto"
    if token == "bus":
        return "bmtc"
    if token in {"walking"}:
        return "walk"
    if token in {"taxi", "rideshare"}:
        return "cab"
    return token


def collapse_mode_tokens(modes: Sequence[str]) -> Tuple[str, ...]:
    """Normalize mode tokens and collapse consecutive duplicates."""
    parts: List[str] = []
    for raw in modes:
        token = _normalize_mode_token(raw)
        if not parts or parts[-1] != token:
            parts.append(token)
    return tuple(parts)


def is_redundant_road_only_chain(modes: Sequence[str]) -> bool:
    """
    True for pure road-family chains with multiple road legs and no walk/transit.

    Drops auto→cab, cab→auto, auto→auto, cab→cab, etc.
    Keeps single-leg road OD and any journey with walk/bus/metro backbone.
    """
    normalized = [_normalize_mode_token(m) for m in modes]
    if not normalized:
        return False
    if any(t not in {"auto", "cab"} for t in normalized):
        return False
    return len(normalized) > 1


def audit_mode_signature(modes: Sequence[str]) -> str:
    collapsed = collapse_mode_tokens(modes)
    return " → ".join(collapsed) if collapsed else ""


def transit_pattern(modes: Sequence[str]) -> Tuple[str, ...]:
    """Transit-only projection of a mode sequence (audit / stop heuristics)."""
    return tuple(m for m in collapse_mode_tokens(modes) if m in {"bmtc", "metro"})


def structural_key(journey: Journey) -> Tuple[Any, ...]:
    """
    Structural identity for diversity retention.

    Uses mode sequence + transit route ids (not OD-specific templates).
    """
    routes = tuple(
        sorted(
            {
                leg.route_id
                for leg in journey.legs
                if leg.route_id
                and leg.mode.value in {"bus", "metro"}
            }
        )
    )
    return (collapse_mode_tokens(journey.modes), routes)


def select_diverse_journeys(
    journeys: List[Journey],
    *,
    max_candidates: int,
    per_signature: int = 3,
) -> Tuple[List[Journey], Dict[str, Any]]:
    """
    Retain structurally distinct journeys up to ``max_candidates``.

    Round-robins across mode signatures (arrival/sort order preserved
    within each signature). Does not invent modes or force quotas by mode family.
    """
    if max_candidates <= 0 or not journeys:
        return [], {
            "diverse_selected": 0,
            "per_signature_cap": per_signature,
            "redundant_road_chains_pruned": 0,
        }

    by_sig: Dict[Tuple[str, ...], List[Journey]] = defaultdict(list)
    order: List[Tuple[str, ...]] = []
    road_pruned = 0
    for j in journeys:
        if is_redundant_road_only_chain(j.modes):
            road_pruned += 1
            continue
        sig = collapse_mode_tokens(j.modes)
        if sig not in by_sig:
            order.append(sig)
        if len(by_sig[sig]) < per_signature:
            by_sig[sig].append(j)

    selected: List[Journey] = []
    idx = {s: 0 for s in order}
    while len(selected) < max_candidates:
        progressed = False
        for sig in order:
            i = idx[sig]
            bucket = by_sig[sig]
            if i < len(bucket):
                selected.append(bucket[i])
                idx[sig] = i + 1
                progressed = True
                if len(selected) >= max_candidates:
                    break
        if not progressed:
            break

    return selected, {
        "diverse_selected": len(selected),
        "per_signature_cap": per_signature,
        "signatures_considered": len(order),
        "signature_list": [" → ".join(s) for s in order],
        "redundant_road_chains_pruned": road_pruned,
    }


def select_diverse_partials(
    partials: List[Any],
    *,
    max_keep: int,
    per_signature: int = 3,
    modes_attr: str = "modes",
) -> Tuple[List[Any], Dict[str, int]]:
    """Filter search partials by collapsed mode signature (pre-materialize)."""
    counts: Counter = Counter()
    kept: List[Any] = []
    skipped = 0
    road_pruned = 0
    for p in partials:
        modes = getattr(p, modes_attr)
        if is_redundant_road_only_chain(modes):
            road_pruned += 1
            continue
        sig = collapse_mode_tokens(modes)
        if counts[sig] >= per_signature:
            skipped += 1
            continue
        counts[sig] += 1
        kept.append(p)
        if len(kept) >= max_keep:
            break
    return kept, {
        "partials_kept": len(kept),
        "partials_skipped_duplicate_signature": skipped,
        "unique_signatures": len(counts),
        "redundant_road_chains_pruned": road_pruned,
    }
