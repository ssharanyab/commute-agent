#!/usr/bin/env python3
"""
Phase 6E — real journey enrichment & Decision Engine audit.

Uses real Phase 6D candidate discovery. Maps enrichment is optional
(mocked when GOOGLE_MAPS_API_KEY unavailable — never fabricates live traffic).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.capabilities.adapt import journeys_to_route_candidates
from src.agent.capabilities.enrichment_apply import apply_enrichments
from src.agent.capabilities.historical import get_historical_context
from src.agent.capabilities.traffic import enrich_road_legs
from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import (
    PROFILE_BALANCED,
    PROFILE_CHEAPEST,
    PROFILE_FASTEST,
    PROFILE_LOW_TRAFFIC,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    UserPreferences,
    preference_profile,
)
from src.journey_builder import (
    DynamicJourneyBuilder,
    JourneyBuildRequest,
    JourneyConstraints,
    SearchLimits,
)
from src.journey_builder.diversity import audit_mode_signature
from src.network.file_repository import FileStaticMobilityRepository


PROFILES = [
    PROFILE_FASTEST,
    PROFILE_CHEAPEST,
    PROFILE_LOW_WALKING,
    PROFILE_RELIABLE,
    PROFILE_LOW_TRAFFIC,
    PROFILE_BALANCED,
]


def _mock_routes_factory():
    """Deterministic Maps stand-in: distance from haversine-ish coords, no fabricate traffic label."""

    def get_routes(origin, destination, departure_time=None, modes=None):
        from src.decision_engine.models import RouteCandidate
        from src.journey_builder.graph import haversine_m

        o_lat, o_lon = [float(x) for x in origin.split(",")]
        d_lat, d_lon = [float(x) for x in destination.split(",")]
        dist = haversine_m(o_lat, o_lon, d_lat, d_lon)
        # ~25 km/h structural stand-in — provenance marks simulation
        minutes = max(3.0, (dist / 1000.0) / 25.0 * 60.0)
        return [
            RouteCandidate(
                route_id="mock",
                mode="drive",
                travel_time_minutes=round(minutes, 2),
                cost=0.0,
                walking_minutes=0.0,
                transfers=0,
                congestion_score=0.35,
                reliability_score=0.7,
                disruption_risk=0.1,
                distance_meters=int(dist * 1.2),  # road factor
                cost_status="unknown",
            )
        ]

    return get_routes


def _segment_audit(journey) -> List[Dict[str, Any]]:
    rows = []
    for leg in journey.legs:
        rows.append(
            {
                "index": leg.index,
                "mode": leg.mode.value,
                "segment_role": leg.segment_role.value,
                "edge_kind": leg.edge_kind.value,
                "distance_meters": leg.distance_meters,
                "duration_seconds": leg.duration_seconds,
                "duration_status": leg.duration_status,
                "cost_inr": leg.cost_inr,
                "cost_status": leg.cost_status,
                "walking_meters": leg.walking_meters,
                "needs_enrichment": leg.needs_enrichment,
                "provenance": leg.provenance.to_dict() if leg.provenance else None,
                "traffic_info": leg.metadata.get("traffic_info"),
                "enrichment_failure": leg.metadata.get("enrichment_failure"),
            }
        )
    return rows


def _de_input_audit(cand) -> Dict[str, Any]:
    return {
        "journey_id": cand.route_id,
        "mode": cand.mode,
        "mode_signature": cand.mode_signature,
        "component_modes": cand.component_modes,
        "travel_time_minutes": cand.travel_time_minutes,
        "duration_status": cand.duration_status,
        "cost": cand.cost,
        "cost_status": cand.cost_status,
        "partial_known_cost_inr": cand.partial_known_cost_inr,
        "walking_minutes": cand.walking_minutes,
        "access_walking_meters": cand.access_walking_meters,
        "transfer_walking_meters": cand.transfer_walking_meters,
        "egress_walking_meters": cand.egress_walking_meters,
        "transfers": cand.transfers,
        "congestion_score": cand.congestion_score,
        "distance_meters": cand.distance_meters,
        "historical_context": cand.historical_mobility_signal,
        "has_polyline": bool(cand.google_polyline),
    }


def run_od(
    builder: DynamicJourneyBuilder,
    *,
    label: str,
    olat: float,
    olon: float,
    dlat: float,
    dlon: float,
    get_routes,
    use_live_maps: bool,
) -> Dict[str, Any]:
    departure = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
    limits = SearchLimits(
        allow_road_access=True,
        allow_direct_road=True,
        max_candidates=20,
        max_nodes_explored=5000,
    )
    t0 = time.perf_counter()
    build = builder.build(
        JourneyBuildRequest(
            origin_lat=olat,
            origin_lon=olon,
            destination_lat=dlat,
            destination_lon=dlon,
            departure_time=departure,
            search_limits=limits,
        )
    )
    t_build = time.perf_counter() - t0
    journeys = list(build.candidates)

    t1 = time.perf_counter()
    enrichment_map: Dict[str, List] = {}
    for j in journeys:
        if j.enrichment_requirements:
            enrichment_map[j.candidate_id] = enrich_road_legs(
                j,
                get_routes=get_routes,
                departure_time=departure.isoformat(),
            )
    journeys = apply_enrichments(journeys, enrichment_map)
    t_enrich = time.perf_counter() - t1

    t2 = time.perf_counter()
    historical = get_historical_context(
        origin_zone=None,
        destination_zone=None,
        hour=departure.hour,
    )
    t_hist = time.perf_counter() - t2

    t3 = time.perf_counter()
    route_cands = journeys_to_route_candidates(
        journeys, enrichments=enrichment_map, historical=historical
    )
    t_adapt = time.perf_counter() - t3

    profile_results = []
    t4 = time.perf_counter()
    for profile in PROFILES:
        prefs = preference_profile(profile)
        ev = evaluate_routes(route_cands, prefs)
        winner = next(
            (c for c in route_cands if c.route_id == ev.recommended_route.route_id),
            None,
        ) if ev.recommended_route else None
        profile_results.append(
            {
                "profile": profile,
                "winner_id": ev.recommended_route.route_id if ev.recommended_route else None,
                "winner_mode": winner.mode if winner else None,
                "winner_signature": winner.mode_signature if winner else None,
                "winner_cost_status": winner.cost_status if winner else None,
                "winner_duration_status": winner.duration_status if winner else None,
                "top_scores": [
                    {
                        "route_id": s.route.route_id,
                        "score": s.final_score,
                        "mode": s.route.mode,
                        "signature": s.route.mode_signature,
                    }
                    for s in (ev.ranked_routes or [])[:5]
                ],
            }
        )
    t_decision = time.perf_counter() - t4

    # Constraint checks
    constraint_checks = []
    for excluded, label_c in (
        (["cab"], "exclude_cab"),
        (["auto_rickshaw"], "exclude_auto"),
        (["cab", "auto_rickshaw"], "exclude_cab_and_auto"),
    ):
        prefs = UserPreferences(excluded_modes=excluded)
        ev = evaluate_routes(route_cands, prefs)
        winner = (
            next(
                (
                    c
                    for c in route_cands
                    if c.route_id == ev.recommended_route.route_id
                ),
                None,
            )
            if ev.recommended_route
            else None
        )
        bad = False
        if winner and winner.component_modes:
            for m in winner.component_modes:
                if m in excluded or (m == "auto" and "auto_rickshaw" in excluded):
                    bad = True
        constraint_checks.append(
            {
                "case": label_c,
                "excluded": excluded,
                "winner_id": winner.route_id if winner else None,
                "winner_modes": winner.component_modes if winner else None,
                "violation": bad,
            }
        )

    candidate_enrichment = []
    for j in journeys:
        candidate_enrichment.append(
            {
                "journey_id": j.candidate_id,
                "mode_signature": j.mode_signature
                or audit_mode_signature(j.modes),
                "segment_count": len(j.legs),
                "segments": _segment_audit(j),
                "total_duration_seconds": j.total_duration_seconds,
                "duration_status": j.duration_status,
                "total_cost_inr": j.total_cost_inr,
                "cost_status": j.cost_status,
                "walking_distance_meters": j.walking_distance_meters,
                "access_walking_meters": j.access_walking_meters,
                "transfer_walking_meters": j.transfer_walking_meters,
                "egress_walking_meters": j.egress_walking_meters,
                "provenance_sources": j.provenance_sources,
                "enrichment_requirement_count": len(j.enrichment_requirements),
            }
        )

    # Pick representative scenarios by signature keywords
    scenarios = {}
    for j in journeys:
        sig = (j.mode_signature or "").lower()
        modes = set(j.modes)
        if modes == {"cab"} and "A" not in scenarios:
            scenarios["A_road_direct_cab"] = j.candidate_id
        if modes == {"auto_rickshaw"} and "B" not in scenarios:
            scenarios["B_road_direct_auto"] = j.candidate_id
        if "bus" in modes and "metro" not in modes and "walk" in modes and "C" not in scenarios:
            scenarios["C_walk_bmtc_walk"] = j.candidate_id
        if "bus" in modes and "metro" in modes and "D" not in scenarios:
            scenarios["D_bmtc_metro"] = j.candidate_id
        if "metro" in modes and "bus" not in modes and "E" not in scenarios:
            scenarios["E_metro"] = j.candidate_id
        if "metro" in modes and ("cab" in modes or "auto_rickshaw" in modes) and "F" not in scenarios:
            scenarios["F_multimodal_road_transit"] = j.candidate_id

    return {
        "label": label,
        "origin": [olat, olon],
        "destination": [dlat, dlon],
        "maps_mode": "live" if use_live_maps else "simulated_structural",
        "timing": {
            "journey_builder_seconds": round(t_build, 3),
            "google_routes_enrichment_seconds": round(t_enrich, 3),
            "historical_seconds": round(t_hist, 3),
            "adapt_seconds": round(t_adapt, 3),
            "decision_engine_seconds": round(t_decision, 3),
            "total_seconds": round(t_build + t_enrich + t_hist + t_adapt + t_decision, 3),
        },
        "candidate_count": len(journeys),
        "scenario_ids": scenarios,
        "candidate_enrichment": candidate_enrichment,
        "decision_engine_inputs": [_de_input_audit(c) for c in route_cands],
        "decision_profiles": profile_results,
        "constraint_checks": constraint_checks,
        "historical": historical.to_dict() if historical else None,
        "unknown_field_cases": [
            {
                "journey_id": c.route_id,
                "cost_status": c.cost_status,
                "duration_status": c.duration_status,
                "signature": c.mode_signature,
            }
            for c in route_cands
            if c.cost_status != "known" or c.duration_status != "known"
        ],
        "aggregation_checks": [
            {
                "journey_id": j.candidate_id,
                "walking_sum_components": round(
                    j.access_walking_meters
                    + j.transfer_walking_meters
                    + j.egress_walking_meters,
                    2,
                ),
                "walking_total": j.walking_distance_meters,
                "walking_components_match_or_subset": (
                    j.access_walking_meters
                    + j.transfer_walking_meters
                    + j.egress_walking_meters
                )
                <= j.walking_distance_meters + 0.01,
            }
            for j in journeys
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("data/mobility_network"))
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=Path("data/mobility_network/audit/phase6e_enrichment.json"),
    )
    parser.add_argument(
        "--live-maps",
        action="store_true",
        help="Use real Google Routes when API key present",
    )
    args = parser.parse_args()

    repo = FileStaticMobilityRepository(args.repo_root)
    if repo.get_active_snapshot("bmtc") is None:
        raise SystemExit("Need BMTC snapshot")
    builder = DynamicJourneyBuilder(repo)

    use_live = bool(args.live_maps and os.getenv("GOOGLE_MAPS_API_KEY"))
    get_routes = None
    if use_live:
        from src.mobility.service import get_candidate_routes as get_routes
    else:
        get_routes = _mock_routes_factory()

    ods = [
        (
            "Electronic City → Majestic",
            ELECTRONIC_CITY.latitude,
            ELECTRONIC_CITY.longitude,
            MAJESTIC.latitude,
            MAJESTIC.longitude,
        ),
        (
            "Indiranagar → Nadaprabhu Kempegowda (Majestic)",
            12.978333,
            77.638664,
            12.975708,
            77.572876,
        ),
    ]

    reports = [
        run_od(
            builder,
            label=label,
            olat=olat,
            olon=olon,
            dlat=dlat,
            dlon=dlon,
            get_routes=get_routes,
            use_live_maps=use_live,
        )
        for label, olat, olon, dlat, dlon in ods
    ]

    out = {
        "phase": "6E",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "maps_mode": "live" if use_live else "simulated_structural",
        "unknown_value_semantics": {
            "cost_unknown": (
                "cost_status=unknown; Decision Engine cost norm=0.5 (neutral mid-scale); "
                "CHEAPEST category considers known-cost candidates only; "
                "never treated as ₹0 free. Transit fares often unknown → known auto "
                "estimates can win CHEAPEST without fabricating bus/metro prices."
            ),
            "duration_unknown": (
                "duration_status=unknown when any road leg lacks Maps or transit "
                "lacks authoritative schedule; ranking uses sum of known leg minutes "
                "only; reliability capped; road times not invented when Maps fails."
            ),
            "historical_missing": "no historical planning penalty",
            "weather": "optional/not_configured — unused by Decision Engine",
        },
        "od_pairs": reports,
        "notes": [
            "Simulated Maps stand-in is structural only — not live traffic.",
            "No cab fares fabricated.",
            "Search algorithm unchanged from Phase 6D.",
        ],
    }
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"audit_written={args.audit_out}")
    for r in reports:
        print(
            r["label"],
            "n=",
            r["candidate_count"],
            "t=",
            r["timing"],
            "scenarios=",
            list(r["scenario_ids"].keys()),
        )
        for p in r["decision_profiles"]:
            print(
                " ",
                p["profile"],
                "→",
                p["winner_signature"] or p["winner_mode"],
                f"(cost={p['winner_cost_status']})",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
