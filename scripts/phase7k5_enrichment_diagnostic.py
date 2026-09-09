#!/usr/bin/env python3
"""
Phase 7K-5 diagnostic: Google Routes enrichment before Decision Engine.

Runs MobilityOrchestrator (ADK path) with Maps ON vs OFF.
Requires GOOGLE_MAPS_API_KEY for Maps-ON case.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC, BENGALURU_LANDMARKS
from src.agent.orchestrator import MobilityOrchestrator, OrchestratorRequest, plan_commute_with_adk
from src.decision_engine.models import preference_profile
from src.journey_builder import JourneyEndpoint, SearchLimits
from src.journey_builder.models import ValueStatus
from src.mobility.geocoding import maps_api_key_configured
from src.network.file_repository import FileStaticMobilityRepository


# Cap Maps spend during diagnostic (still exercises multi-leg enrichment).
_DIAG_LIMITS = SearchLimits(max_candidates=8)


def _station(repo, sid: str) -> Tuple[float, float]:
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stations") or []:
            if str(raw.get("id")) == sid:
                return float(raw["latitude"]), float(raw["longitude"])
    raise KeyError(sid)


def _classify(c) -> str:
    modes = [m.lower() for m in (c.component_modes or [c.mode])]
    sig = (c.mode_signature or "").lower()
    if "metro" in modes or "metro" in sig:
        return "metro"
    if "bus" in modes or "bus" in sig:
        return "bmtc"
    if "auto" in modes or "auto" in sig:
        return "auto"
    if "cab" in modes or c.mode == "cab":
        return "cab"
    return c.mode or "other"


def _road_legs(journey):
    out = []
    for leg in journey.legs:
        if leg.needs_enrichment or leg.mode.value in {"cab", "auto_rickshaw"}:
            out.append(leg)
        elif leg.edge_kind.value in {"road_access", "road_direct"}:
            out.append(leg)
    return out


def _dump_candidate(j, before_legs: Optional[Dict] = None) -> Dict[str, Any]:
    roads = _road_legs(j)
    return {
        "candidate_id": j.candidate_id,
        "mode_signature": j.mode_signature,
        "duration_status": j.duration_status,
        "total_duration_seconds": j.total_duration_seconds,
        "walking_distance_meters": j.walking_distance_meters,
        "cost": j.total_cost_inr,
        "cost_status": j.cost_status,
        "road_legs": [
            {
                "index": l.index,
                "mode": l.mode.value,
                "edge_id": l.edge_id,
                "distance_meters": l.distance_meters,
                "duration_seconds": l.duration_seconds,
                "duration_status": l.duration_status,
                "needs_enrichment": l.needs_enrichment,
                "provenance": l.provenance.to_dict() if l.provenance else None,
            }
            for l in roads
        ],
    }


def run_case(
    repo,
    *,
    label: str,
    origin: str,
    destination: str,
    o_lat: float,
    o_lon: float,
    d_lat: float,
    d_lon: float,
    profile: str,
    invoke_live_traffic: bool,
    o_ep: Optional[JourneyEndpoint] = None,
    d_ep: Optional[JourneyEndpoint] = None,
) -> Dict[str, Any]:
    req = OrchestratorRequest(
        user_id="diag-7k5",
        origin=origin,
        destination=destination,
        departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
        origin_lat=o_lat,
        origin_lon=o_lon,
        destination_lat=d_lat,
        destination_lon=d_lon,
        origin_endpoint=o_ep,
        destination_endpoint=d_ep,
        preferences=preference_profile(profile),
        search_limits=_DIAG_LIMITS,
        invoke_live_traffic=invoke_live_traffic,
        invoke_gemini=False,
        invoke_weather=False,
        invoke_historical=False,
    )
    # plan_commute_with_adk = ADK entry → MobilityOrchestrator.run
    result = plan_commute_with_adk(req, repository=repo)

    caps = {c.name: c.to_dict() for c in (result.metadata.capabilities or [])}
    enrich_cap = caps.get("traffic_enrichment") or {}

    # RouteCandidate dump entering DE (already ranked, but values are inputs)
    rc_rows = []
    for c in result.route_candidates:
        rc_rows.append(
            {
                "candidate_id": c.route_id,
                "mode_signature": c.mode_signature,
                "kind": _classify(c),
                "travel_time_minutes": c.travel_time_minutes,
                "duration_status": c.duration_status,
                "distance_meters": c.distance_meters,
                "cost": c.cost,
                "cost_status": c.cost_status,
                "walking_distance_meters": c.walking_distance_meters,
                "transfers": c.transfers,
                "reliability": c.reliability_score,
                "congestion": c.congestion_score,
            }
        )

    ranked = []
    if result.evaluation:
        for i, sr in enumerate(result.evaluation.ranked_routes, 1):
            if not sr.is_valid:
                continue
            ranked.append(
                {
                    "rank": i,
                    "kind": _classify(sr.route),
                    "route_id": sr.route.route_id,
                    "score": round(sr.final_score, 4),
                    "time_min": sr.route.travel_time_minutes,
                    "duration_status": sr.route.duration_status,
                    "cost": sr.route.cost,
                    "cost_status": sr.route.cost_status,
                    "sig": sr.route.mode_signature,
                }
            )

    journeys_dump = [_dump_candidate(j) for j in result.journeys]

    return {
        "label": label,
        "profile": profile,
        "maps_on": invoke_live_traffic,
        "candidate_count": len(result.journeys),
        "road_enrichment_reqs": sum(
            len(j.enrichment_requirements) for j in result.journeys
        ),
        "traffic_capability": enrich_cap,
        "maps_calls_attempted": (enrich_cap.get("detail") or {}).get(
            "maps_calls_attempted"
        ),
        "maps_calls_successful": (enrich_cap.get("detail") or {}).get(
            "maps_calls_successful"
        ),
        "maps_calls_failed": (enrich_cap.get("detail") or {}).get("maps_calls_failed"),
        "journeys": journeys_dump,
        "route_candidates": rc_rows,
        "ranked": ranked[:12],
        "winner": ranked[0] if ranked else None,
        "adk_path": "plan_commute_with_adk → MobilityOrchestrator → JB → enrich_road_legs → apply_enrichments → journeys_to_route_candidates → evaluate_routes",
    }


def main():
    # Prefer .env without shell override pollution
    from dotenv import load_dotenv

    load_dotenv(override=True)

    repo = FileStaticMobilityRepository(Path("data/mobility_network"))
    maps_ok = maps_api_key_configured()
    print(f"GOOGLE_MAPS_API_KEY configured: {maps_ok}")

    maj_st = _station(repo, "nadaprabhu_kempegowda")
    mg_st = _station(repo, "mg_road")
    ind = BENGALURU_LANDMARKS["indiranagar"]
    mg_area = (12.9754, 77.6065)

    scenarios = [
        (
            "A Majestic → MG Road",
            "Majestic",
            "MG Road",
            MAJESTIC.latitude,
            MAJESTIC.longitude,
            mg_area[0],
            mg_area[1],
            None,
            None,
        ),
        (
            "B Majestic Metro → MG Road Metro",
            "Majestic Metro",
            "MG Road Metro",
            maj_st[0],
            maj_st[1],
            mg_st[0],
            mg_st[1],
            JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:nadaprabhu_kempegowda",
                lat=maj_st[0],
                lon=maj_st[1],
            ),
            JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:mg_road",
                lat=mg_st[0],
                lon=mg_st[1],
            ),
        ),
        (
            "C Majestic → Indiranagar",
            "Majestic",
            "Indiranagar",
            MAJESTIC.latitude,
            MAJESTIC.longitude,
            ind.latitude,
            ind.longitude,
            None,
            None,
        ),
        (
            "D Electronic City → Majestic",
            "Electronic City",
            "Majestic",
            ELECTRONIC_CITY.latitude,
            ELECTRONIC_CITY.longitude,
            MAJESTIC.latitude,
            MAJESTIC.longitude,
            None,
            None,
        ),
    ]

    reports = []
    for label, o, d, ola, olo, dla, dlo, oep, dep in scenarios:
        for profile in ("BALANCED", "FASTEST"):
            for maps_on in (False, True):
                if maps_on and not maps_ok:
                    print(f"SKIP Maps-ON {label} {profile} (no API key)")
                    continue
                print(f"\n>>> {label} | {profile} | maps={'ON' if maps_on else 'OFF'}")
                rep = run_case(
                    repo,
                    label=label,
                    origin=o,
                    destination=d,
                    o_lat=ola,
                    o_lon=olo,
                    d_lat=dla,
                    d_lon=dlo,
                    profile=profile,
                    invoke_live_traffic=maps_on,
                    o_ep=oep,
                    d_ep=dep,
                )
                reports.append(rep)
                print(
                    f"  candidates={rep['candidate_count']} "
                    f"road_reqs={rep['road_enrichment_reqs']} "
                    f"maps_ok={rep['maps_calls_successful']}/"
                    f"{rep['maps_calls_attempted']} "
                    f"fail={rep['maps_calls_failed']}"
                )
                if rep["winner"]:
                    w = rep["winner"]
                    print(
                        f"  winner={w['kind']} {w['route_id']} "
                        f"score={w['score']} time={w['time_min']} "
                        f"({w['duration_status']}) sig={w['sig']}"
                    )
                # Sample road-containing journeys
                for j in rep["journeys"]:
                    if not j["road_legs"]:
                        continue
                    print(f"  journey {j['candidate_id']} {j['mode_signature']}")
                    for rl in j["road_legs"]:
                        print(
                            f"    road[{rl['index']}] {rl['mode']} "
                            f"dur={rl['duration_seconds']} "
                            f"status={rl['duration_status']} "
                            f"dist={rl['distance_meters']} "
                            f"prov={(rl['provenance'] or {}).get('notes')}"
                        )

    # FASTEST summary table
    print("\n\n=== FASTEST SUMMARY (Maps ON) ===")
    for rep in reports:
        if rep["profile"] != "FASTEST" or not rep["maps_on"]:
            continue
        best = {}
        for row in rep["ranked"]:
            best.setdefault(row["kind"], row)
        print(f"\n{rep['label']}")
        for kind in ("metro", "bmtc", "auto", "cab"):
            b = best.get(kind)
            if b:
                print(
                    f"  {kind}: rank={b['rank']} time={b['time_min']} "
                    f"status={b['duration_status']} sig={b['sig']}"
                )
            else:
                print(f"  {kind}: absent")

    out_path = Path("scripts/phase7k5_enrichment_report.json")
    out_path.write_text(json.dumps(reports, indent=2, default=str))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
