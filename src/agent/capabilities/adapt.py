"""Adapt Journey Builder candidates → Decision Engine RouteCandidates."""

from __future__ import annotations

from typing import Dict, List, Optional

from src.agent.capabilities import (
    HistoricalCapabilityResult,
    TrafficEnrichmentResult,
)
from src.decision_engine.models import RouteCandidate
from src.journey_builder.models import Journey

WALK_M_PER_MIN = 80.0
BUS_M_PER_MIN = 250.0  # structural estimate only when schedule/live missing
METRO_M_PER_MIN = 500.0


def journeys_to_route_candidates(
    journeys: List[Journey],
    *,
    enrichments: Optional[Dict[str, List[TrafficEnrichmentResult]]] = None,
    historical: Optional[HistoricalCapabilityResult] = None,
) -> List[RouteCandidate]:
    """
    Convert structural journeys into RouteCandidates for deterministic ranking.

    Missing live times are estimated only from published distances with explicit
    low reliability — never from Gemini. Enrichment durations override estimates.
    """
    enrichments = enrichments or {}
    out: List[RouteCandidate] = []
    for journey in journeys:
        by_leg = {
            e.leg_index: e
            for e in enrichments.get(journey.candidate_id, [])
            if e.available
        }
        travel_min = 0.0
        used_estimate = False
        used_enrichment = False
        for leg in journey.legs:
            if leg.index in by_leg and by_leg[leg.index].duration_minutes is not None:
                travel_min += float(by_leg[leg.index].duration_minutes)
                used_enrichment = True
                continue
            dist = float(leg.distance_meters or 0.0)
            if leg.mode.value == "walk":
                travel_min += dist / WALK_M_PER_MIN if dist else 0.0
            elif leg.mode.value == "metro":
                travel_min += (dist / METRO_M_PER_MIN) if dist else 8.0
                used_estimate = True
            elif leg.mode.value == "bus":
                travel_min += (dist / BUS_M_PER_MIN) if dist else 12.0
                used_estimate = True
            elif leg.needs_enrichment:
                # Road leg without enrichment — do not invent traffic time.
                used_estimate = True
                travel_min += (dist / 400.0) if dist else 15.0
            else:
                travel_min += 5.0
                used_estimate = True

        walk_min = journey.walking_distance_meters / WALK_M_PER_MIN
        modes = journey.modes
        if len(set(modes)) > 1:
            mode_label = "hybrid"
        elif modes:
            mode_label = modes[0]
        else:
            mode_label = "unknown"

        reliability = 0.75
        congestion = 0.35
        hist_signal = None
        if historical and historical.coverage:
            hist_signal = dict(historical.signal)
            if historical.reliability is not None:
                reliability = float(historical.reliability)
            if historical.expected_duration_minutes is not None and mode_label in {
                "cab",
                "auto_rickshaw",
                "hybrid",
            }:
                # Soft context only — Decision Engine still ranks; do not replace
                # transit structural times silently for pure transit.
                pass

        if used_estimate and not used_enrichment:
            reliability = min(reliability, 0.55)

        # Polyline from first successful enrichment if any
        polyline = None
        token = None
        for e in enrichments.get(journey.candidate_id, []):
            if e.available and e.polyline:
                polyline = e.polyline
                token = e.route_token
                break

        # Prefer known journey-level fare; never invent cab/transit prices.
        cost_val = 0.0
        if (
            journey.cost_status == "known"
            and journey.total_cost_inr is not None
        ):
            cost_val = float(journey.total_cost_inr)

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
                component_modes=list(modes),
            )
        )
    return out
