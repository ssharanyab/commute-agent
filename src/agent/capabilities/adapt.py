"""Adapt Journey Builder candidates → Decision Engine RouteCandidates."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.agent.capabilities import (
    HistoricalCapabilityResult,
    TrafficEnrichmentResult,
)
from src.decision_engine.models import RouteCandidate
from src.journey_builder.models import Journey, ValueStatus

WALK_M_PER_MIN = 80.0
BUS_M_PER_MIN = 250.0  # structural estimate only when schedule/live missing
METRO_M_PER_MIN = 500.0


def _leg_duration_minutes(
    leg,
    enrichment: Optional[TrafficEnrichmentResult],
) -> Tuple[Optional[float], str]:
    """
    Return (minutes, status) for one leg.

    Road legs without enrichment: unknown (do not invent traffic time).
    Transit without schedule: structural estimate with status unknown.
    Walk: geometric estimate with status known.
    """
    if enrichment is not None and enrichment.available and enrichment.duration_minutes is not None:
        return float(enrichment.duration_minutes), ValueStatus.KNOWN.value

    if leg.duration_status == ValueStatus.KNOWN.value and leg.duration_seconds is not None:
        return float(leg.duration_seconds) / 60.0, ValueStatus.KNOWN.value

    if leg.duration_status == ValueStatus.UNAVAILABLE.value:
        return None, ValueStatus.UNAVAILABLE.value

    # Prefer builder-supplied structural estimate seconds (still unknown).
    if (
        leg.duration_status == ValueStatus.UNKNOWN.value
        and leg.duration_seconds is not None
    ):
        return float(leg.duration_seconds) / 60.0, ValueStatus.UNKNOWN.value

    dist = float(leg.distance_meters or 0.0)
    mode = leg.mode.value
    if mode == "walk":
        return (dist / WALK_M_PER_MIN if dist else 0.0), ValueStatus.KNOWN.value
    if mode == "metro":
        # Structural only — no authoritative timetable in published snapshot.
        # Do not invent a fixed minute count when distance is missing.
        if dist <= 0:
            return None, ValueStatus.UNKNOWN.value
        return (dist / METRO_M_PER_MIN), ValueStatus.UNKNOWN.value
    if mode == "bus":
        if dist <= 0:
            return None, ValueStatus.UNKNOWN.value
        return (dist / BUS_M_PER_MIN), ValueStatus.UNKNOWN.value
    if leg.needs_enrichment or mode in {"cab", "auto_rickshaw"}:
        # No Maps result — duration unknown (not fabricated).
        return None, ValueStatus.UNKNOWN.value
    return None, ValueStatus.UNKNOWN.value


def journeys_to_route_candidates(
    journeys: List[Journey],
    *,
    enrichments: Optional[Dict[str, List[TrafficEnrichmentResult]]] = None,
    historical: Optional[HistoricalCapabilityResult] = None,
) -> List[RouteCandidate]:
    """
    Convert structural journeys into RouteCandidates for deterministic ranking.

    Cost: known journey total when available; otherwise cost_status=unknown
    with cost=0.0 as a non-scoring placeholder (Decision Engine treats unknown
    as neutral — never as free).

    Duration: prefers per-leg enrichment / known leg times; road legs without
    enrichment contribute unknown (not invented). Travel time used for ranking
    is the sum of known leg minutes only when any unknown remains — marked
    duration_status=unknown and reliability capped.
    """
    enrichments = enrichments or {}
    out: List[RouteCandidate] = []
    for journey in journeys:
        by_leg = {
            e.leg_index: e
            for e in enrichments.get(journey.candidate_id, [])
        }
        travel_min = 0.0
        any_unknown_duration = False
        any_unavailable_duration = False
        used_enrichment = False
        known_or_structural_minutes = False
        congestion_scores: List[float] = []
        total_distance = 0.0

        for leg in journey.legs:
            if leg.distance_meters is not None:
                total_distance += float(leg.distance_meters)
            enr = by_leg.get(leg.index)
            minutes, status = _leg_duration_minutes(leg, enr)
            if enr is not None and enr.available:
                used_enrichment = True
                ti = enr.traffic_info or {}
                if ti.get("congestion_score") is not None:
                    try:
                        congestion_scores.append(float(ti["congestion_score"]))
                    except (TypeError, ValueError):
                        pass
            elif leg.metadata.get("traffic_info", {}).get("congestion_score") is not None:
                try:
                    congestion_scores.append(
                        float(leg.metadata["traffic_info"]["congestion_score"])
                    )
                except (TypeError, ValueError):
                    pass

            if status == ValueStatus.UNAVAILABLE.value:
                any_unavailable_duration = True
            elif status == ValueStatus.UNKNOWN.value:
                any_unknown_duration = True
            if minutes is not None:
                travel_min += minutes
                known_or_structural_minutes = True

        # Prefer post-enrichment journey aggregate when fully known.
        if (
            journey.duration_status == ValueStatus.KNOWN.value
            and journey.total_duration_seconds is not None
        ):
            travel_min = float(journey.total_duration_seconds) / 60.0
            duration_status = ValueStatus.KNOWN.value
            known_or_structural_minutes = True
        elif any_unavailable_duration:
            duration_status = ValueStatus.UNAVAILABLE.value
        elif any_unknown_duration:
            duration_status = ValueStatus.UNKNOWN.value
        else:
            duration_status = ValueStatus.KNOWN.value

        # Never present unknown/unavailable road-only duration as 0 minutes.
        # (Scoring still receives duration_status; 0 would look falsely fastest.)
        if (
            duration_status != ValueStatus.KNOWN.value
            and not known_or_structural_minutes
        ):
            travel_min = 24.0 * 60.0  # explicit non-zero sentinel; status remains unknown

        walk_min = journey.walking_distance_meters / WALK_M_PER_MIN
        modes = journey.modes
        if len(set(modes)) > 1:
            mode_label = "hybrid"
        elif modes:
            mode_label = modes[0]
        else:
            mode_label = "unknown"

        reliability = 0.75
        if congestion_scores:
            congestion = sum(congestion_scores) / len(congestion_scores)
        else:
            congestion = 0.35

        hist_signal = None
        if historical and historical.coverage:
            hist_signal = dict(historical.signal)
            if historical.reliability is not None:
                reliability = float(historical.reliability)

        if duration_status != ValueStatus.KNOWN.value:
            reliability = min(reliability, 0.55)
        if not used_enrichment and any(
            l.needs_enrichment or l.mode.value in {"cab", "auto_rickshaw"}
            for l in journey.legs
        ):
            reliability = min(reliability, 0.55)

        polyline = None
        token = None
        for e in enrichments.get(journey.candidate_id, []):
            if e.available and e.polyline:
                polyline = e.polyline
                token = e.route_token
                break
        if polyline is None:
            for leg in journey.legs:
                if leg.metadata.get("polyline"):
                    polyline = leg.metadata["polyline"]
                    token = leg.metadata.get("route_token")
                    break

        cost_status = journey.cost_status or ValueStatus.UNKNOWN.value
        if cost_status == ValueStatus.KNOWN.value and journey.total_cost_inr is not None:
            cost_val = float(journey.total_cost_inr)
            partial = cost_val
        else:
            # Placeholder only — scoring uses cost_status=unknown as neutral.
            cost_val = 0.0
            partial = None
            known_parts = [
                float(l.cost_inr) for l in journey.legs if l.cost_inr is not None
            ]
            if known_parts:
                partial = round(sum(known_parts), 2)

        out.append(
            RouteCandidate(
                route_id=journey.candidate_id,
                mode=mode_label,
                travel_time_minutes=round(travel_min, 2),
                cost=cost_val,
                walking_minutes=round(walk_min, 2),
                transfers=int(journey.transfer_count),
                congestion_score=float(congestion),
                reliability_score=float(reliability),
                disruption_risk=0.1,
                historical_mobility_signal=hist_signal,
                google_polyline=polyline,
                google_route_token=token,
                distance_meters=int(total_distance) if total_distance else None,
                component_modes=list(modes),
                cost_status=cost_status,
                duration_status=duration_status,
                partial_known_cost_inr=partial,
                mode_signature=journey.mode_signature or "",
                access_walking_meters=journey.access_walking_meters,
                transfer_walking_meters=journey.transfer_walking_meters,
                egress_walking_meters=journey.egress_walking_meters,
                walking_distance_meters=float(journey.walking_distance_meters)
                if journey.walking_distance_meters is not None
                else None,
            )
        )
    return out
