"""
Phase 7C — Top-5 journey selection with meaningful diversity + grounded reasons.

Presentation layer over already-evaluated journeys. Does not change the
Decision Engine's authoritative recommendation (always rank 1 when present).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.agent.mobility_strategy import MobilityStrategy
from src.decision_engine.models import (
    PROFILE_BALANCED,
    PROFILE_CHEAPEST,
    PROFILE_FASTEST,
    PROFILE_LOW_TRAFFIC,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    EvaluationResult,
    RouteCandidate,
    ScoredRoute,
    UserPreferences,
)
from src.decision_engine.strategy import (
    classify_backbone,
    has_public_transport_backbone,
    has_road_transport_backbone,
    strategy_tier_key,
    total_walking_meters,
)

MAX_TOP_JOURNEYS = 5

# Diversity signature uses pipe-separated canonical modes (not route IDs).
_MODE_ALIASES = {
    "walking": "walk",
    "walk": "walk",
    "auto_rickshaw": "auto",
    "rickshaw": "auto",
    "tuk_tuk": "auto",
    "auto": "auto",
    "taxi": "cab",
    "drive": "cab",
    "rideshare": "cab",
    "cab": "cab",
    "bmtc": "bus",
    "bus": "bus",
    "bmrcl": "metro",
    "metro": "metro",
}


def normalize_diversity_mode(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    token = str(getattr(raw, "value", raw)).strip().lower().replace("-", "_")
    if not token or token in {"hybrid", "unknown", "mixed", "transit", "public_transport"}:
        return None
    return _MODE_ALIASES.get(token, token)


def candidate_mode_sequence(candidate: RouteCandidate) -> Tuple[str, ...]:
    """Normalized mode sequence for diversity (consecutive duplicates collapsed)."""
    raw_parts: List[Any] = []
    if candidate.component_modes:
        raw_parts = list(candidate.component_modes)
    elif candidate.mode_signature:
        text = (
            candidate.mode_signature.replace("→", "|")
            .replace("->", "|")
        )
        raw_parts = [p.strip() for p in text.split("|") if p.strip()]
    elif candidate.mode:
        raw_parts = [candidate.mode]

    parts: List[str] = []
    for raw in raw_parts:
        token = normalize_diversity_mode(raw)
        if not token:
            continue
        if not parts or parts[-1] != token:
            parts.append(token)
    return tuple(parts)


def diversity_signature(candidate: RouteCandidate) -> str:
    """
    Meaningful journey-structure key for Top-5 deduplication.

    Primary key: collapsed transport-mode sequence (access/backbone/egress).
    Does NOT include BMTC/BMRCL route IDs — route 500 vs 500A collapse together.
    """
    seq = candidate_mode_sequence(candidate)
    return "|".join(seq) if seq else (normalize_diversity_mode(candidate.mode) or "unknown")


def infer_preference_profile(preferences: Optional[UserPreferences]) -> str:
    if preferences is None:
        return PROFILE_BALANCED
    weights = {
        PROFILE_FASTEST: float(preferences.time_weight),
        PROFILE_CHEAPEST: float(preferences.cost_weight),
        PROFILE_LOW_WALKING: float(preferences.walking_weight),
        PROFILE_RELIABLE: float(preferences.reliability_weight),
        PROFILE_LOW_TRAFFIC: float(preferences.congestion_weight),
    }
    best_name, best_val = max(weights.items(), key=lambda kv: kv[1])
    if best_val <= 1.5:
        return PROFILE_BALANCED
    # Distinct soft-profile signal (named profiles use 8.0 on the focus axis).
    return best_name


def _duration_known(c: RouteCandidate) -> bool:
    return str(getattr(c, "duration_status", "known") or "known").lower() == "known"


def _cost_known(c: RouteCandidate) -> bool:
    return str(getattr(c, "cost_status", "known") or "known").lower() == "known"


def _walking_known(c: RouteCandidate) -> Tuple[bool, Optional[float]]:
    meters, status = total_walking_meters(c)
    if status != "known" or meters is None:
        return False, None
    return True, float(meters)


@dataclass
class TopJourneyOption:
    route_id: str
    candidate_id: str
    mode: str
    mode_signature: str
    diversity_signature: str
    component_modes: List[str]
    duration: Optional[float]
    cost: Optional[float]
    cost_status: str
    duration_status: str
    walking_distance_meters: Optional[float]
    transfers: int
    score: float
    rank: int
    strategy_tier: int
    is_recommended: bool
    reason: str
    backbone: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id,
            "candidate_id": self.candidate_id,
            "mode": self.mode,
            "mode_signature": self.mode_signature,
            "diversity_signature": self.diversity_signature,
            "component_modes": list(self.component_modes),
            "duration": self.duration,
            "cost": self.cost if _cost_known_status(self.cost_status) else None,
            "cost_status": self.cost_status,
            "duration_status": self.duration_status,
            "walking_distance_meters": self.walking_distance_meters,
            "transfers": self.transfers,
            "score": round(self.score, 2),
            "rank": self.rank,
            "strategy_tier": self.strategy_tier,
            "is_recommended": self.is_recommended,
            "reason": self.reason,
            "backbone": self.backbone,
            "steps": list(self.steps),
        }


def _cost_known_status(status: str) -> bool:
    return str(status or "known").lower() == "known"


@dataclass
class TopJourneySelection:
    recommended: Optional[TopJourneyOption]
    alternatives: List[TopJourneyOption] = field(default_factory=list)
    selected_count: int = 0
    max_count: int = MAX_TOP_JOURNEYS

    @property
    def options(self) -> List[TopJourneyOption]:
        out: List[TopJourneyOption] = []
        if self.recommended is not None:
            out.append(self.recommended)
        out.extend(self.alternatives)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "selected_count": self.selected_count,
            "max_count": self.max_count,
            "top_journeys": [o.to_dict() for o in self.options],
        }


def _sort_key(
    sr: ScoredRoute,
    strategy: Optional[MobilityStrategy],
) -> Tuple[int, float, str]:
    return (
        strategy_tier_key(sr.route, strategy),
        -float(sr.final_score),
        sr.route.route_id,
    )


def _option_from_scored(
    sr: ScoredRoute,
    *,
    rank: int,
    is_recommended: bool,
    reason: str,
    strategy: Optional[MobilityStrategy],
) -> TopJourneyOption:
    route = sr.route
    walk_ok, walk_m = _walking_known(route)
    modes = list(candidate_mode_sequence(route))
    sig = diversity_signature(route)
    display_sig = route.mode_signature or " → ".join(modes) or route.mode
    return TopJourneyOption(
        route_id=route.route_id,
        candidate_id=route.route_id,
        mode=route.mode,
        mode_signature=display_sig,
        diversity_signature=sig,
        component_modes=modes,
        duration=float(route.travel_time_minutes) if _duration_known(route) else None,
        cost=float(route.cost) if _cost_known(route) else None,
        cost_status=str(route.cost_status or "known"),
        duration_status=str(route.duration_status or "known"),
        walking_distance_meters=walk_m if walk_ok else None,
        transfers=int(route.transfers),
        score=float(sr.final_score),
        rank=rank,
        strategy_tier=strategy_tier_key(route, strategy),
        is_recommended=is_recommended,
        reason=reason,
        backbone=classify_backbone(route).value,
    )


def _minutes_delta_phrase(faster_by: float) -> Optional[str]:
    mins = int(round(faster_by))
    if mins < 1:
        return None
    return f"About {mins} min faster than the next option"


def _grounded_reason(
    candidate: RouteCandidate,
    *,
    is_recommended: bool,
    recommended: Optional[RouteCandidate],
    selected_peers: Sequence[RouteCandidate],
    preferences: Optional[UserPreferences],
    strategy: Optional[MobilityStrategy],
) -> str:
    """Deterministic, data-grounded reason. Never invents unknown comparisons."""
    profile = infer_preference_profile(preferences)
    peers = list(selected_peers)
    others = [p for p in peers if p.route_id != candidate.route_id]

    def fastest_claim() -> Optional[str]:
        if not _duration_known(candidate):
            return None
        known = [p for p in peers if _duration_known(p)]
        if len(known) < 2:
            # Alone among known — only claim if sole peer set with known duration.
            if len(known) == 1 and known[0].route_id == candidate.route_id:
                return "Fastest option" if is_recommended else None
            return None
        best = min(known, key=lambda p: (p.travel_time_minutes, p.route_id))
        if best.route_id != candidate.route_id:
            return None
        rest = [p for p in known if p.route_id != candidate.route_id]
        if not rest:
            return "Fastest option"
        nxt = min(rest, key=lambda p: (p.travel_time_minutes, p.route_id))
        delta = float(nxt.travel_time_minutes) - float(candidate.travel_time_minutes)
        phrase = _minutes_delta_phrase(delta)
        if is_recommended and phrase:
            return phrase
        return "Fastest option"

    def cheapest_claim() -> Optional[str]:
        if not _cost_known(candidate):
            return None
        known = [p for p in peers if _cost_known(p)]
        if len(known) < 2:
            return None
        best = min(known, key=lambda p: (p.cost, p.route_id))
        if best.route_id != candidate.route_id:
            return None
        return "Lowest-cost option"

    def walking_claim() -> Optional[str]:
        ok, meters = _walking_known(candidate)
        if not ok or meters is None:
            return None
        if recommended is not None and candidate.route_id != recommended.route_id:
            rok, rm = _walking_known(recommended)
            if rok and rm is not None and meters < rm:
                return "Less walking than the recommended option"
        known_peers = []
        for p in peers:
            pok, pm = _walking_known(p)
            if pok and pm is not None:
                known_peers.append((p, pm))
        if len(known_peers) < 2:
            return None
        best = min(known_peers, key=lambda t: (t[1], t[0].route_id))
        if best[0].route_id == candidate.route_id:
            return "Least walking among these options"
        return None

    def transfers_claim() -> Optional[str]:
        if recommended is None or candidate.route_id == recommended.route_id:
            # Among peers
            if not others:
                return None
            if all(candidate.transfers < p.transfers for p in others):
                return "Fewer transfers"
            return None
        if candidate.transfers < recommended.transfers:
            return "Fewer transfers"
        return None

    def reliability_claim() -> Optional[str]:
        # Only comparative when peer reliability scores differ meaningfully.
        if not others:
            return None
        mine = float(candidate.reliability_score)
        better = all(mine > float(p.reliability_score) + 1e-9 for p in others)
        if better:
            return "More reliable among these options"
        if recommended and candidate.route_id != recommended.route_id:
            if mine > float(recommended.reliability_score) + 1e-9:
                return "More reliable than the recommended option"
        return None

    def traffic_claim() -> Optional[str]:
        if not others:
            return None
        mine = float(candidate.congestion_score)
        better = all(mine < float(p.congestion_score) - 1e-9 for p in others)
        if better:
            return "Lower traffic among these options"
        if recommended and candidate.route_id != recommended.route_id:
            if mine < float(recommended.congestion_score) - 1e-9:
                return "Lower traffic than the recommended option"
        return None

    def structural_claim() -> Optional[str]:
        if has_public_transport_backbone(candidate):
            if strategy == MobilityStrategy.PUBLIC_TRANSPORT_FIRST:
                return "Uses public transport as the main part of the journey"
            return "Public transport backbone"
        if has_road_transport_backbone(candidate):
            modes = candidate_mode_sequence(candidate)
            road_only = all(
                normalize_diversity_mode(m) in {"auto", "cab", "walk"} for m in modes
            ) and any(normalize_diversity_mode(m) in {"auto", "cab"} for m in modes)
            if road_only and len([m for m in modes if m in {"auto", "cab"}]) == 1:
                return "Direct road journey"
            return "Road transport journey"
        return None

    priority: List[Any]
    if profile == PROFILE_FASTEST:
        priority = [fastest_claim, transfers_claim, walking_claim, structural_claim]
    elif profile == PROFILE_CHEAPEST:
        priority = [cheapest_claim, walking_claim, transfers_claim, structural_claim]
    elif profile == PROFILE_LOW_WALKING:
        priority = [walking_claim, fastest_claim, transfers_claim, structural_claim]
    elif profile == PROFILE_RELIABLE:
        priority = [reliability_claim, fastest_claim, walking_claim, structural_claim]
    elif profile == PROFILE_LOW_TRAFFIC:
        priority = [traffic_claim, fastest_claim, walking_claim, structural_claim]
    else:
        priority = [
            fastest_claim,
            cheapest_claim,
            walking_claim,
            transfers_claim,
            reliability_claim,
            traffic_claim,
            structural_claim,
        ]

    claims: List[str] = []
    for fn in priority:
        claim = fn()
        if claim and claim not in claims:
            claims.append(claim)
        if len(claims) >= 2:
            break

    if is_recommended:
        base = "Best match for your preferences"
        support = None
        for c in claims:
            if c.startswith("About ") or c in {
                "Fastest option",
                "Lowest-cost option",
                "Least walking among these options",
                "Fewer transfers",
                "More reliable among these options",
                "Lower traffic among these options",
            }:
                support = c
                break
        if support and support != base:
            return f"{base} · {support}"
        return base

    if claims:
        return claims[0]
    return "Another option that fits your preferences"


def select_top_journeys(
    evaluation: EvaluationResult,
    preferences: Optional[UserPreferences] = None,
    *,
    strategy: Optional[MobilityStrategy] = None,
    max_count: int = MAX_TOP_JOURNEYS,
) -> TopJourneySelection:
    """
    Select up to ``max_count`` meaningfully diverse valid journeys.

    Rank 1 is always ``evaluation.recommended_route`` when present.
    Invalid / hard-constraint failures never appear.
    Preferred strategy tier is filled before inferior-tier fallback.
    """
    max_count = max(0, int(max_count))
    empty = TopJourneySelection(
        recommended=None,
        alternatives=[],
        selected_count=0,
        max_count=max_count,
    )
    if max_count == 0 or evaluation.recommended_route is None:
        return empty

    valid = [sr for sr in evaluation.ranked_routes if sr.is_valid]
    if not valid:
        return empty

    by_id = {sr.route.route_id: sr for sr in valid}
    rec = evaluation.recommended_route
    if rec.route_id not in by_id:
        # Safety: recommended must be valid.
        return empty

    ordered = sorted(valid, key=lambda sr: _sort_key(sr, strategy))
    best_tier = strategy_tier_key(rec, strategy)
    preferred = [
        sr for sr in ordered if strategy_tier_key(sr.route, strategy) == best_tier
    ]
    inferior = [
        sr for sr in ordered if strategy_tier_key(sr.route, strategy) > best_tier
    ]

    selected: List[ScoredRoute] = []
    used_sigs: set = set()

    rec_sr = by_id[rec.route_id]
    selected.append(rec_sr)
    used_sigs.add(diversity_signature(rec_sr.route))

    def absorb(pool: List[ScoredRoute]) -> None:
        for sr in pool:
            if len(selected) >= max_count:
                return
            if sr.route.route_id == rec.route_id:
                continue
            sig = diversity_signature(sr.route)
            if sig in used_sigs:
                continue
            used_sigs.add(sig)
            selected.append(sr)

    absorb(preferred)
    if len(selected) < max_count:
        absorb(inferior)

    peer_routes = [sr.route for sr in selected]
    options: List[TopJourneyOption] = []
    for idx, sr in enumerate(selected):
        is_rec = idx == 0
        reason = _grounded_reason(
            sr.route,
            is_recommended=is_rec,
            recommended=rec,
            selected_peers=peer_routes,
            preferences=preferences,
            strategy=strategy,
        )
        # Guard: never expose raw scores / internal ids in reason text.
        if str(sr.final_score) in reason or sr.route.route_id in reason:
            reason = (
                "Best match for your preferences"
                if is_rec
                else "Another option that fits your preferences"
            )
        options.append(
            _option_from_scored(
                sr,
                rank=idx + 1,
                is_recommended=is_rec,
                reason=reason,
                strategy=strategy,
            )
        )

    recommended_opt = options[0]
    alts = options[1:]
    return TopJourneySelection(
        recommended=recommended_opt,
        alternatives=alts,
        selected_count=len(options),
        max_count=max_count,
    )
