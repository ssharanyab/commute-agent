#!/usr/bin/env python3
"""
Phase 7K-6 diagnostic: authoritative BMRCL token fares → RouteCandidate → DE.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC
from src.agent.orchestrator import MobilityOrchestrator, OrchestratorRequest, plan_commute_with_adk
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import preference_profile
from src.journey_builder import JourneyEndpoint
from src.journey_builder.constraints import SearchLimits
from src.network.file_repository import FileStaticMobilityRepository
from src.network.transit_fares import fare_for_stations_travelled

_DIAG_LIMITS = SearchLimits(max_candidates=10)


def _station(repo, sid: str) -> Tuple[float, float, str]:
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stations") or []:
            if str(raw.get("id")) == sid:
                return float(raw["latitude"]), float(raw["longitude"]), str(raw["name"])
    raise KeyError(sid)


def _fare_rows(journeys) -> List[Dict[str, Any]]:
    rows = []
    for j in journeys:
        metros = [l for l in j.legs if l.mode.value == "metro"]
        if not metros:
            continue
        rows.append(
            {
                "candidate_id": j.candidate_id,
                "mode_signature": j.mode_signature,
                "total_cost_inr": j.total_cost_inr,
                "cost_status": j.cost_status,
                "metro_legs": [
                    {
                        "from": l.from_ref or l.from_name,
                        "to": l.to_ref or l.to_name,
                        "route_id": l.route_id,
                        "stations_travelled": (l.metadata or {}).get(
                            "stations_travelled"
                        ),
                        "cost_inr": l.cost_inr,
                        "cost_status": l.cost_status,
                        "cost_meta": (l.metadata or {}).get("cost_meta"),
                    }
                    for l in metros
                ],
            }
        )
    return rows


def _winners(cands) -> Dict[str, Any]:
    out = {}
    for profile in ("FASTEST", "CHEAPEST", "BALANCED"):
        ev = evaluate_routes(cands, preference_profile(profile))
        cats = {}
        for cat in ev.route_categories or []:
            r = cat.route
            cats[cat.category] = {
                "route_id": r.route_id,
                "mode": r.mode,
                "mode_signature": r.mode_signature,
                "cost": r.cost if r.cost_status == "known" else None,
                "cost_status": r.cost_status,
                "travel_time_minutes": r.travel_time_minutes,
                "duration_status": r.duration_status,
            }
        out[profile] = cats
    return out


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
    o_ep: Optional[JourneyEndpoint] = None,
    d_ep: Optional[JourneyEndpoint] = None,
) -> Dict[str, Any]:
    req = OrchestratorRequest(
        user_id="diag-7k6",
        origin=origin,
        destination=destination,
        departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
        origin_lat=o_lat,
        origin_lon=o_lon,
        destination_lat=d_lat,
        destination_lon=d_lon,
        origin_endpoint=o_ep,
        destination_endpoint=d_ep,
        preferences=preference_profile("BALANCED"),
        search_limits=_DIAG_LIMITS,
        invoke_live_traffic=False,
        invoke_gemini=False,
        invoke_weather=False,
        invoke_historical=False,
    )
    result = plan_commute_with_adk(req, repository=repo)
    return {
        "label": label,
        "candidate_count": len(result.journeys),
        "metro_fares": _fare_rows(result.journeys),
        "category_by_preference": _winners(result.route_candidates),
    }


def main() -> None:
    load_dotenv(override=True)
    root = Path(__file__).resolve().parents[1]
    repo = FileStaticMobilityRepository(root / "data" / "mobility_network")

    majestic = _station(repo, "nadaprabhu_kempegowda")
    mg = _station(repo, "mg_road")
    indir = _station(repo, "indiranagar")
    jaya = _station(repo, "jayanagar")

    report: Dict[str, Any] = {
        "phase": "7K-6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_token_fares_from_topology": {
            "majestic_to_mg_road": {
                "stations": 4,
                "fare_inr": fare_for_stations_travelled(4)[0],
            },
            "majestic_to_indiranagar": {
                "stations": 7,
                "fare_inr": fare_for_stations_travelled(7)[0],
            },
            "jayanagar_to_majestic": {
                "stations": 6,
                "fare_inr": fare_for_stations_travelled(6)[0],
            },
        },
        "ods": [],
    }

    report["ods"].append(
        run_case(
            repo,
            label="1. Majestic → MG Road (place)",
            origin="Majestic",
            destination="MG Road",
            o_lat=MAJESTIC.latitude,
            o_lon=MAJESTIC.longitude,
            d_lat=mg[0],
            d_lon=mg[1],
        )
    )
    report["ods"].append(
        run_case(
            repo,
            label="2. Majestic Metro → MG Road Metro",
            origin=majestic[2],
            destination=mg[2],
            o_lat=majestic[0],
            o_lon=majestic[1],
            d_lat=mg[0],
            d_lon=mg[1],
            o_ep=JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:nadaprabhu_kempegowda",
                lat=majestic[0],
                lon=majestic[1],
                display_name=majestic[2],
            ),
            d_ep=JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:mg_road",
                lat=mg[0],
                lon=mg[1],
                display_name=mg[2],
            ),
        )
    )
    report["ods"].append(
        run_case(
            repo,
            label="3. Majestic → Indiranagar",
            origin="Majestic",
            destination="Indiranagar",
            o_lat=MAJESTIC.latitude,
            o_lon=MAJESTIC.longitude,
            d_lat=indir[0],
            d_lon=indir[1],
            d_ep=JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:indiranagar",
                lat=indir[0],
                lon=indir[1],
                display_name=indir[2],
            ),
        )
    )
    report["ods"].append(
        run_case(
            repo,
            label="4. Jayanagar → Majestic",
            origin=jaya[2],
            destination=majestic[2],
            o_lat=jaya[0],
            o_lon=jaya[1],
            d_lat=majestic[0],
            d_lon=majestic[1],
            o_ep=JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:jayanagar",
                lat=jaya[0],
                lon=jaya[1],
                display_name=jaya[2],
            ),
            d_ep=JourneyEndpoint.network_node(
                network="bmrcl",
                node_id="station:nadaprabhu_kempegowda",
                lat=majestic[0],
                lon=majestic[1],
                display_name=majestic[2],
            ),
        )
    )
    report["ods"].append(
        run_case(
            repo,
            label="5. Electronic City → Majestic",
            origin=ELECTRONIC_CITY.name,
            destination=MAJESTIC.name,
            o_lat=ELECTRONIC_CITY.latitude,
            o_lon=ELECTRONIC_CITY.longitude,
            d_lat=MAJESTIC.latitude,
            d_lon=MAJESTIC.longitude,
        )
    )

    out = root / "scripts" / "phase7k6_fare_diagnostic_out.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    # Compact console summary
    for od in report["ods"]:
        print(f"\n=== {od['label']} ===")
        print(f"candidates={od['candidate_count']} metro_rows={len(od['metro_fares'])}")
        for row in od["metro_fares"][:3]:
            print(
                f"  {row['mode_signature']}: cost={row['total_cost_inr']} "
                f"status={row['cost_status']} legs={row['metro_legs']}"
            )
        for pref, cats in od["category_by_preference"].items():
            w = {
                k: (v or {}).get("mode_signature") or (v or {}).get("mode")
                for k, v in cats.items()
                if k in {"FASTEST", "CHEAPEST", "BEST_OVERALL"}
            }
            print(f"  [{pref}] {w}")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
