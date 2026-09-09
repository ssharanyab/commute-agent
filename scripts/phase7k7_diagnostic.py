#!/usr/bin/env python3
"""
Phase 7K-7 DIAGNOSTIC ONLY — Majestic → MG Road path-loss investigation.

Does NOT modify Journey Builder, Decision Engine, fares, enrichment, ADK, or Flutter.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from src.agent.demo_od import ELECTRONIC_CITY, MAJESTIC, BENGALURU_LANDMARKS
from src.api.schemas import PlanRequest
from src.api.service import execute_plan, orchestrator_request_from_plan
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import preference_profile
from src.decision_engine.strategy import strategy_tier_key, classify_backbone
from src.journey_builder import DynamicJourneyBuilder, JourneyEndpoint, SearchLimits
from src.journey_builder.diversity import collapse_mode_tokens
from src.journey_builder.economics import METRO_M_PER_S
from src.journey_builder.graph import haversine_m, station_node_id
from src.journey_builder.models import JourneyBuildRequest
from src.network.file_repository import FileStaticMobilityRepository
from src.network.transit_fares import fare_for_stations_travelled

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / "phase7k7_diagnostic_report.json"
API = os.getenv("COMMUTE_API", "http://127.0.0.1:8000")


def _station(repo, sid: str) -> Dict[str, Any]:
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stations") or []:
            if str(raw.get("id")) == sid:
                return dict(raw)
    raise KeyError(sid)


def _mg_road_coords(repo) -> Tuple[float, float, str]:
    s = _station(repo, "mg_road")
    return float(s["latitude"]), float(s["longitude"]), str(s["name"])


def _classify_suspicious(sig: str) -> Optional[str]:
    tokens = [t.strip().lower() for t in sig.replace("→", "->").split("->")]
    tokens = [t.replace("auto_rickshaw", "auto") for t in tokens]
    joined = " → ".join(tokens)
    patterns = [
        ("auto", "cab"),
        ("cab", "auto"),
        ("auto", "bus", "auto"),
        ("auto", "bus", "cab"),
        ("cab", "bus", "auto"),
        ("cab", "bus", "cab"),
        ("auto", "metro", "auto"),
        ("cab", "metro", "cab"),
    ]
    for p in patterns:
        if tokens == list(p):
            return joined
    # Also catch longer containing auto→cab adjacent
    for i in range(len(tokens) - 1):
        if {tokens[i], tokens[i + 1]} == {"auto", "cab"}:
            return joined
    if "bus" in tokens and tokens.count("auto") + tokens.count("cab") >= 2:
        return joined
    return None


def _leg_dump(leg, graph_nodes=None) -> Dict[str, Any]:
    from_name = leg.from_name
    to_name = leg.to_name
    if graph_nodes:
        fn = graph_nodes.get(leg.from_node_id)
        tn = graph_nodes.get(leg.to_node_id)
        if fn and not from_name:
            from_name = fn.name
        if tn and not to_name:
            to_name = tn.name
    cm = (leg.metadata or {}).get("cost_meta") or {}
    return {
        "mode": leg.mode.value,
        "edge_kind": leg.edge_kind.value if leg.edge_kind else None,
        "from_node_id": leg.from_node_id,
        "from_name": from_name,
        "from_ref": leg.from_ref,
        "to_node_id": leg.to_node_id,
        "to_name": to_name,
        "to_ref": leg.to_ref,
        "distance_meters": leg.distance_meters,
        "duration_seconds": leg.duration_seconds,
        "duration_status": leg.duration_status,
        "cost_inr": leg.cost_inr,
        "cost_status": leg.cost_status,
        "route_id": leg.route_id,
        "provider": leg.provider,
        "stations_travelled": (leg.metadata or {}).get("stations_travelled"),
        "is_transfer": leg.is_transfer,
        "segment_role": leg.segment_role.value if leg.segment_role else None,
        "fare_kind": cm.get("fare_kind"),
        "needs_enrichment": leg.needs_enrichment,
    }


def _journey_metrics(j, o_lat, o_lon, d_lat, d_lon) -> Dict[str, Any]:
    legs = list(j.legs)
    access_m = 0.0
    egress_m = 0.0
    road_m = 0.0
    walk_m = float(j.walking_distance_meters or 0.0)
    first_metro = None
    metro_seq = []
    for i, leg in enumerate(legs):
        dist = float(leg.distance_meters or 0.0)
        if leg.mode.value in {"auto_rickshaw", "cab", "bus"} or (
            leg.edge_kind and leg.edge_kind.value in {"road_access", "road_direct"}
        ):
            road_m += dist
        if i == 0 and leg.mode.value in {"walk", "auto_rickshaw", "cab"}:
            access_m = dist
        if i == len(legs) - 1 and leg.mode.value in {"walk", "auto_rickshaw", "cab"}:
            egress_m = dist
        if leg.mode.value == "metro":
            if first_metro is None:
                first_metro = {
                    "station_id": leg.from_ref,
                    "station_name": leg.from_name,
                    "node_id": leg.from_node_id,
                    "access_leg_mode": legs[0].mode.value if legs else None,
                    "access_distance_m": access_m if i > 0 else dist,
                }
            metro_seq.append(leg.from_ref)
            metro_seq.append(leg.to_ref)
    # unique order-preserving station sequence
    seq: List[str] = []
    for s in metro_seq:
        if s and (not seq or seq[-1] != s):
            seq.append(s)
    geo = haversine_m(o_lat, o_lon, d_lat, d_lon) if None not in (o_lat, o_lon, d_lat, d_lon) else None
    return {
        "candidate_id": j.candidate_id,
        "mode_signature": j.mode_signature,
        "canonical_signature": " → ".join(collapse_mode_tokens(j.modes)),
        "transfer_count": j.transfer_count,
        "leg_count": len(legs),
        "total_cost_inr": j.total_cost_inr,
        "cost_status": j.cost_status,
        "total_duration_seconds": j.total_duration_seconds,
        "duration_status": j.duration_status,
        "walking_distance_meters": walk_m,
        "access_walking_meters": j.access_walking_meters,
        "egress_walking_meters": j.egress_walking_meters,
        "origin_access_distance_m": access_m,
        "destination_egress_distance_m": egress_m,
        "total_road_distance_m": round(road_m, 1),
        "total_geographic_od_m": round(geo, 1) if geo is not None else None,
        "first_metro": first_metro,
        "metro_station_sequence": seq,
        "legs": [_leg_dump(l) for l in legs],
    }


def _expected_direct_metro(repo) -> Dict[str, Any]:
    m = _station(repo, "nadaprabhu_kempegowda")
    g = _station(repo, "mg_road")
    hops = abs(int(m["line_order"]["purple"]) - int(g["line_order"]["purple"]))
    fare, status, meta = fare_for_stations_travelled(hops)
    # structural duration from haversine hops along purple
    purple = None
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for r in payload.get("routes") or []:
            if r.get("id") == "purple":
                purple = r.get("stop_ids") or []
    # path stations exclusive of origin
    oi = purple.index("nadaprabhu_kempegowda")
    gi = purple.index("mg_road")
    lo, hi = (oi, gi) if oi < gi else (gi, oi)
    seq = purple[lo : hi + 1]
    if oi > gi:
        seq = list(reversed(seq))
    dist = 0.0
    stations = {s["id"]: s for p in repo._all_active_payloads() for s in (p.get("stations") or [])}  # noqa
    for a, b in zip(seq, seq[1:]):
        sa, sb = stations[a], stations[b]
        dist += haversine_m(sa["latitude"], sa["longitude"], sb["latitude"], sb["longitude"])
    dur = dist / METRO_M_PER_S
    return {
        "mode_signature": "metro",
        "walk_metro_walk_signature": "walk → metro → walk",
        "station_ids": seq,
        "station_names": [stations[s]["name"] for s in seq],
        "line_id": "purple",
        "line_name": "Purple Line",
        "metro_hops_stations_travelled": hops,
        "fare_inr": fare,
        "fare_status": status,
        "fare_meta": meta,
        "structural_distance_m": round(dist, 1),
        "structural_duration_s": round(dur, 1),
        "structural_duration_min": round(dur / 60.0, 2),
        "transfers": 0,
        "origin_station": {
            "id": m["id"],
            "name": m["name"],
            "lat": m["latitude"],
            "lon": m["longitude"],
            "node_id": station_node_id(m["id"]),
        },
        "destination_station": {
            "id": g["id"],
            "name": g["name"],
            "lat": g["latitude"],
            "lon": g["longitude"],
            "node_id": station_node_id(g["id"]),
        },
        "network_supports": True,
    }


def _access_distances(repo, o_lat, o_lon) -> List[Dict[str, Any]]:
    rows = []
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stations") or []:
            if raw.get("latitude") is None:
                continue
            d = haversine_m(o_lat, o_lon, float(raw["latitude"]), float(raw["longitude"]))
            rows.append(
                {
                    "id": raw["id"],
                    "name": raw["name"],
                    "distance_m": round(d, 1),
                    "walk_ok": d <= 800,
                    "road_ok": d <= 5000,
                }
            )
    rows.sort(key=lambda r: r["distance_m"])
    return rows


def _http_plan(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{API}/plan",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 — diagnostic
        return {"ok": False, "http_error": f"{type(exc).__name__}: {exc}"}


def _rc_dump(c, preferences_name: str, scored=None) -> Dict[str, Any]:
    return {
        "route_id": c.route_id,
        "mode": c.mode,
        "mode_signature": c.mode_signature,
        "component_modes": c.component_modes,
        "travel_time_minutes": c.travel_time_minutes,
        "duration_status": c.duration_status,
        "cost": c.cost,
        "cost_status": c.cost_status,
        "walking_minutes": c.walking_minutes,
        "walking_distance_meters": c.walking_distance_meters,
        "transfers": c.transfers,
        "congestion_score": c.congestion_score,
        "reliability_score": c.reliability_score,
        "disruption_risk": c.disruption_risk,
        "historical_mobility_signal": c.historical_mobility_signal,
        "backbone": classify_backbone(c).value,
        "strategy_tier": strategy_tier_key(c, None),
        "preference_profile": preferences_name,
        "final_score": getattr(scored, "final_score", None) if scored else None,
        "is_valid": getattr(scored, "is_valid", None) if scored else None,
    }


def analyze_od(
    repo,
    *,
    label: str,
    origin: str,
    destination: str,
    o_lat: float,
    o_lon: float,
    d_lat: float,
    d_lon: float,
    o_ep: Optional[Dict[str, Any]] = None,
    d_ep: Optional[Dict[str, Any]] = None,
    invoke_live_traffic: bool = False,
) -> Dict[str, Any]:
    """One orchestration pass; DE profiles evaluated offline on same candidates."""
    from src.agent.orchestrator import plan_commute_with_adk

    out: Dict[str, Any] = {"label": label, "invoke_live_traffic": invoke_live_traffic}

    body = PlanRequest(
        origin=origin,
        destination=destination,
        origin_lat=o_lat,
        origin_lon=o_lon,
        destination_lat=d_lat,
        destination_lon=d_lon,
        origin_endpoint=o_ep,
        destination_endpoint=d_ep,
        preference_profile="BALANCED",
        invoke_gemini=False,
        invoke_weather=False,
        invoke_historical=False,
        invoke_live_traffic=invoke_live_traffic,
    )
    orch_req = orchestrator_request_from_plan(body)
    result = plan_commute_with_adk(orch_req, repository=repo)
    journeys = list(result.journeys)
    cands = list(result.route_candidates)

    out["orchestrator"] = {
        "journey_count": len(journeys),
        "route_candidate_count": len(cands),
        "search_metadata": (
            result.journey_build.search_metadata if result.journey_build else None
        ),
        "termination_reason": (
            (result.journey_build.search_metadata or {}).get(
                "search_termination_reason"
            )
            if result.journey_build
            else None
        ),
        "jb_diagnostics": (
            result.journey_build.search_metadata if result.journey_build else None
        ),
        "endpoint_origin": orch_req.origin_endpoint.to_dict()
        if orch_req.origin_endpoint
        else None,
        "endpoint_destination": orch_req.destination_endpoint.to_dict()
        if orch_req.destination_endpoint
        else None,
        "origin_lat": orch_req.origin_lat,
        "origin_lon": orch_req.origin_lon,
        "destination_lat": orch_req.destination_lat,
        "destination_lon": orch_req.destination_lon,
    }

    profiles_payload = {}
    for profile in ("FASTEST", "CHEAPEST", "BALANCED"):
        ev = evaluate_routes(cands, preference_profile(profile))
        valid = [sr for sr in ev.ranked_routes if sr.is_valid]
        profiles_payload[profile] = {
            "resolved_origin_ep": out["orchestrator"]["endpoint_origin"],
            "resolved_destination_ep": out["orchestrator"]["endpoint_destination"],
            "candidate_count": len(cands),
            "recommendation_sig": valid[0].route.mode_signature if valid else None,
            "recommendation_route_id": valid[0].route.route_id if valid else None,
            "top5": [
                {
                    "rank": i,
                    "sig": sr.route.mode_signature,
                    "route_id": sr.route.route_id,
                    "score": round(sr.final_score, 4),
                    "cost": sr.route.cost,
                    "cost_status": sr.route.cost_status,
                    "time_min": sr.route.travel_time_minutes,
                    "duration_status": sr.route.duration_status,
                }
                for i, sr in enumerate(valid[:5], 1)
            ],
            "categories": {
                cat.category: {
                    "sig": cat.route.mode_signature,
                    "route_id": cat.route.route_id,
                    "cost": cat.route.cost,
                    "cost_status": cat.route.cost_status,
                }
                for cat in (ev.route_categories or [])
            },
        }
    out["profiles"] = profiles_payload

    metro_rows = []
    for j in journeys:
        if "metro" not in collapse_mode_tokens(j.modes):
            continue
        metro_rows.append(_journey_metrics(j, o_lat, o_lon, d_lat, d_lon))
    metro_rows.sort(
        key=lambda r: (
            (r.get("first_metro") or {}).get("access_distance_m")
            if (r.get("first_metro") or {}).get("access_distance_m") is not None
            else 1e12,
            r.get("destination_egress_distance_m") or 1e12,
            r.get("walking_distance_meters") or 1e12,
            r.get("transfer_count") or 99,
            r.get("total_geographic_od_m") or 1e12,
        )
    )
    out["metro_candidates_sorted"] = metro_rows

    jb = DynamicJourneyBuilder(repository=repo)
    jb_req = JourneyBuildRequest(
        origin_lat=o_lat,
        origin_lon=o_lon,
        destination_lat=d_lat,
        destination_lon=d_lon,
        origin_endpoint=orch_req.origin_endpoint,
        destination_endpoint=orch_req.destination_endpoint,
        departure_time=orch_req.departure_time,
    )
    jb_res = jb.build(jb_req)
    jb_journeys = list(jb_res.candidates)
    jb_sigs = sorted(
        {" → ".join(collapse_mode_tokens(j.modes)) for j in jb_journeys}
    )
    walk_metro_walk = any(
        collapse_mode_tokens(j.modes) == ("walk", "metro", "walk")
        for j in jb_journeys
    )
    pure_metro = any(
        collapse_mode_tokens(j.modes) == ("metro",) for j in jb_journeys
    )
    direct_boarding = []
    for j in jb_journeys:
        metros = [l for l in j.legs if l.mode.value == "metro"]
        if not metros:
            continue
        if metros[0].from_ref == "nadaprabhu_kempegowda":
            direct_boarding.append(
                {
                    "sig": j.mode_signature,
                    "from": metros[0].from_ref,
                    "to": metros[-1].to_ref,
                    "stations": (metros[0].metadata or {}).get("stations_travelled"),
                    "cost": j.total_cost_inr,
                    "cost_status": j.cost_status,
                }
            )
    meta = jb_res.search_metadata or {}
    out["journey_builder_direct"] = {
        "journey_count": len(jb_journeys),
        "signatures": jb_sigs,
        "walk_metro_walk_generated": walk_metro_walk,
        "pure_metro_generated": pure_metro,
        "direct_majestic_boarding_examples": direct_boarding[:12],
        "search_metadata": meta,
        "generated_mode_signatures": meta.get("generated_mode_signatures"),
        "origin_access_nodes": meta.get("origin_access_nodes"),
        "destination_access_nodes": meta.get("destination_access_nodes"),
        "access_discovery_walk_access_rail_found": meta.get(
            "access_discovery_walk_access_rail_found"
        ),
        "candidates_generated": meta.get("candidates_generated"),
        "dominance_pruned": meta.get("dominance_pruned"),
        "duplicate_signature_skipped": meta.get("duplicate_signature_skipped"),
        "search_termination_reason": meta.get("search_termination_reason"),
    }

    access_rows = _access_distances(repo, o_lat, o_lon)
    out["access_station_distances_from_origin"] = access_rows[:15]
    majestic_dist = next(
        (r["distance_m"] for r in access_rows if r["id"] == "nadaprabhu_kempegowda"),
        None,
    )
    attiguppe_dist = next(
        (r["distance_m"] for r in access_rows if r["id"] == "attaluru"),
        None,
    )

    attiguppe = []
    o_access = meta.get("origin_access_nodes") or []
    for j in journeys:
        metros = [l for l in j.legs if l.mode.value == "metro"]
        if not metros or metros[0].from_ref != "attaluru":
            continue
        mrow = _journey_metrics(j, o_lat, o_lon, d_lat, d_lon)
        mrow["distance_origin_to_majestic_metro_m"] = majestic_dist
        mrow["distance_origin_to_attiguppe_m"] = attiguppe_dist
        mrow["attaluru_in_origin_access_nodes"] = any(
            "attaluru" in str(x) for x in o_access
        )
        mrow["majestic_in_origin_access_nodes"] = any(
            "nadaprabhu_kempegowda" in str(x) for x in o_access
        )
        attiguppe.append(mrow)
    out["attiguppe_metro_candidates"] = attiguppe

    suspicious = []
    ev_bal = evaluate_routes(cands, preference_profile("BALANCED"))
    scored_by_sig = {sr.route.mode_signature: sr for sr in ev_bal.ranked_routes}
    for j in journeys:
        sig = j.mode_signature or " → ".join(collapse_mode_tokens(j.modes))
        tokens = collapse_mode_tokens(j.modes)
        kind = _classify_suspicious(sig)
        if not kind:
            if "metro" in tokens:
                continue
            roadish = [t for t in tokens if t in {"auto", "cab", "bus"}]
            if len(roadish) >= 2 and "bus" in tokens:
                kind = sig
            elif tokens in {("auto", "cab"), ("cab", "auto")}:
                kind = sig
            else:
                continue
        metrics = _journey_metrics(j, o_lat, o_lon, d_lat, d_lon)
        if tokens in {("auto", "cab"), ("cab", "auto")}:
            clazz, why = (
                "C",
                "road→road mode change with no transit; dominated by single-mode road",
            )
        elif (
            tokens
            and tokens[0] in {"auto", "cab"}
            and tokens[-1] in {"auto", "cab"}
            and "bus" in tokens
        ):
            clazz, why = (
                "B",
                "road-bus-road feasible; often dominated by direct road or walk-metro",
            )
        else:
            clazz, why = ("B", "multimodal but likely redundant")
        metrics["suspicion_class"] = clazz
        metrics["suspicion_why"] = why
        sr = scored_by_sig.get(j.mode_signature)
        if sr:
            metrics["score"] = round(sr.final_score, 4)
        suspicious.append(metrics)
    out["suspicious_candidates"] = suspicious

    scored_by_id = {sr.route.route_id: sr for sr in ev_bal.ranked_routes}

    def pick(pred):
        for c in cands:
            if pred(c):
                return c
        return None

    expected = None
    for j in journeys:
        tok = collapse_mode_tokens(j.modes)
        metros = [l for l in j.legs if l.mode.value == "metro"]
        if (
            tok == ("walk", "metro", "walk")
            and metros
            and metros[0].from_ref == "nadaprabhu_kempegowda"
        ):
            for c in cands:
                if c.route_id == j.candidate_id or c.mode_signature == j.mode_signature:
                    expected = c
                    break
        if expected:
            break
    if expected is None:
        expected = pick(
            lambda c: collapse_mode_tokens(tuple(c.component_modes or [c.mode]))
            in {("walk", "metro", "walk"), ("metro",)}
        )

    best_auto = pick(
        lambda c: collapse_mode_tokens(tuple(c.component_modes or [c.mode]))
        == ("auto",)
    )
    best_cab = pick(
        lambda c: collapse_mode_tokens(tuple(c.component_modes or [c.mode]))
        == ("cab",)
    )
    best_aba = pick(
        lambda c: collapse_mode_tokens(tuple(c.component_modes or [c.mode]))
        == ("auto", "bus", "auto")
    )
    best_att = None
    for j in journeys:
        metros = [l for l in j.legs if l.mode.value == "metro"]
        if metros and metros[0].from_ref == "attaluru":
            for c in cands:
                if c.route_id == j.candidate_id or c.mode_signature == j.mode_signature:
                    best_att = c
                    break
            if best_att:
                break

    out["decision_engine_inputs"] = {
        "expected_or_direct_metro": _rc_dump(
            expected, "BALANCED", scored_by_id.get(expected.route_id)
        )
        if expected
        else None,
        "best_auto": _rc_dump(
            best_auto, "BALANCED", scored_by_id.get(best_auto.route_id)
        )
        if best_auto
        else None,
        "best_cab": _rc_dump(best_cab, "BALANCED", scored_by_id.get(best_cab.route_id))
        if best_cab
        else None,
        "best_auto_bus_auto": _rc_dump(
            best_aba, "BALANCED", scored_by_id.get(best_aba.route_id)
        )
        if best_aba
        else None,
        "best_attiguppe_metro": _rc_dump(
            best_att, "BALANCED", scored_by_id.get(best_att.route_id)
        )
        if best_att
        else None,
        "ranked_top5": [
            {
                "rank": i,
                "route_id": sr.route.route_id,
                "score": round(sr.final_score, 4),
                "sig": sr.route.mode_signature,
                "cost": sr.route.cost,
                "cost_status": sr.route.cost_status,
                "time": sr.route.travel_time_minutes,
                "duration_status": sr.route.duration_status,
            }
            for i, sr in enumerate(
                [s for s in ev_bal.ranked_routes if s.is_valid][:5], 1
            )
        ],
        "categories": profiles_payload["BALANCED"]["categories"],
    }

    gen_sigs = set(meta.get("generated_mode_signatures") or [])
    retained_sigs = set(jb_sigs)
    orch_sigs = {" → ".join(collapse_mode_tokens(j.modes)) for j in journeys}
    wmw = "walk → metro → walk"
    lt = {
        "network_supports_direct_purple": True,
        "jb_generated_walk_metro_walk": walk_metro_walk,
        "jb_generated_pure_metro": pure_metro,
        "in_generated_mode_signatures": wmw in gen_sigs,
        "retained_after_diversity": wmw in retained_sigs,
        "present_in_orchestrator_journeys": wmw in orch_sigs,
        "present_in_route_candidates": any(
            collapse_mode_tokens(tuple(c.component_modes or [c.mode]))
            == ("walk", "metro", "walk")
            for c in cands
        ),
        "attiguppe_present": bool(attiguppe),
        "origin_endpoint_kind": (
            orch_req.origin_endpoint.kind.value if orch_req.origin_endpoint else None
        ),
        "destination_endpoint_kind": (
            orch_req.destination_endpoint.kind.value
            if orch_req.destination_endpoint
            else None
        ),
        "problem_layer_hint": None,
    }
    if not lt["jb_generated_walk_metro_walk"] and not lt["jb_generated_pure_metro"]:
        if wmw in gen_sigs:
            lt["problem_layer_hint"] = "CANDIDATE_RETENTION"
        else:
            lt["problem_layer_hint"] = "JOURNEY_BUILDER_OR_ENDPOINT"
    elif not lt["retained_after_diversity"]:
        lt["problem_layer_hint"] = "CANDIDATE_RETENTION"
    elif not lt["present_in_route_candidates"]:
        lt["problem_layer_hint"] = "ECONOMICS_OR_ADAPT"
    else:
        rank = next(
            (
                i
                for i, sr in enumerate(ev_bal.ranked_routes, 1)
                if sr.is_valid and expected and sr.route.route_id == expected.route_id
            ),
            None,
        )
        lt["expected_metro_rank"] = rank
        if rank and rank > 3:
            lt["problem_layer_hint"] = "DECISION_ENGINE_RANKING_OR_INPUT_QUALITY"
        else:
            lt["problem_layer_hint"] = (
                "PRESENT — check duration_status/enrichment vs competing road modes"
            )
    out["loss_trace"] = lt
    out["http_plan_balanced"] = {
        "skipped": True,
        "reason": "diagnostic uses plan_commute_with_adk (same as /plan)",
    }

    out["generality_flags"] = {
        "direct_metro_generated": bool(
            pure_metro
            or any(
                x.get("from") == "nadaprabhu_kempegowda" and x.get("to") == "mg_road"
                for x in direct_boarding
            )
            or any(
                (r.get("first_metro") or {}).get("station_id")
                == "nadaprabhu_kempegowda"
                and "mg_road" in (r.get("metro_station_sequence") or [])
                for r in metro_rows
            )
        ),
        "walk_metro_walk_generated": bool(walk_metro_walk),
        "attiguppe_detour_present": bool(attiguppe),
        "suspicious_road_combos_present": bool(suspicious),
        "expected_metro_retained": bool(walk_metro_walk or pure_metro),
        "metro_reaches_decision_engine": bool(
            expected
            or any(
                "metro" in (row.get("sig") or "")
                for row in profiles_payload["BALANCED"]["top5"]
            )
        ),
    }
    return out



def main() -> None:
    load_dotenv(override=True)
    repo = FileStaticMobilityRepository(ROOT / "data" / "mobility_network")
    mg_lat, mg_lon, mg_name = _mg_road_coords(repo)
    m = _station(repo, "nadaprabhu_kempegowda")
    indir = _station(repo, "indiranagar")
    jaya = _station(repo, "jayanagar")

    # Maps on if key present (app default)
    maps_on = bool(os.getenv("GOOGLE_MAPS_API_KEY"))

    report: Dict[str, Any] = {
        "phase": "7K-7",
        "diagnostic_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "maps_live": maps_on,
        "expected_direct_metro": _expected_direct_metro(repo),
        "ods": [],
    }

    # 1. Majestic → MG Road (place labels — app-like)
    report["ods"].append(
        analyze_od(
            repo,
            label="1. Majestic → MG Road (place)",
            origin="Majestic",
            destination="MG Road",
            o_lat=MAJESTIC.latitude,
            o_lon=MAJESTIC.longitude,
            d_lat=mg_lat,
            d_lon=mg_lon,
            invoke_live_traffic=False,
        )
    )

    # 2. Majestic → Indiranagar
    report["ods"].append(
        analyze_od(
            repo,
            label="2. Majestic → Indiranagar",
            origin="Majestic",
            destination="Indiranagar",
            o_lat=MAJESTIC.latitude,
            o_lon=MAJESTIC.longitude,
            d_lat=float(indir["latitude"]),
            d_lon=float(indir["longitude"]),
            invoke_live_traffic=False,
        )
    )

    # 3. Jayanagar → Majestic
    report["ods"].append(
        analyze_od(
            repo,
            label="3. Jayanagar → Majestic",
            origin="Jayanagar",
            destination="Majestic",
            o_lat=float(jaya["latitude"]),
            o_lon=float(jaya["longitude"]),
            d_lat=MAJESTIC.latitude,
            d_lon=MAJESTIC.longitude,
            o_ep={
                "kind": "network_node",
                "network": "bmrcl",
                "node_id": "station:jayanagar",
                "lat": float(jaya["latitude"]),
                "lon": float(jaya["longitude"]),
                "display_name": jaya["name"],
            },
            d_ep={
                "kind": "network_node",
                "network": "bmrcl",
                "node_id": "station:nadaprabhu_kempegowda",
                "lat": float(m["latitude"]),
                "lon": float(m["longitude"]),
                "display_name": m["name"],
            },
            invoke_live_traffic=False,
        )
    )

    # 4. MG Road → Indiranagar
    report["ods"].append(
        analyze_od(
            repo,
            label="4. MG Road → Indiranagar",
            origin="MG Road",
            destination="Indiranagar",
            o_lat=mg_lat,
            o_lon=mg_lon,
            d_lat=float(indir["latitude"]),
            d_lon=float(indir["longitude"]),
            invoke_live_traffic=False,
        )
    )

    # 5. Station → station
    report["ods"].append(
        analyze_od(
            repo,
            label="5. Majestic Metro → MG Road Metro (network_node)",
            origin=m["name"],
            destination=mg_name,
            o_lat=float(m["latitude"]),
            o_lon=float(m["longitude"]),
            d_lat=mg_lat,
            d_lon=mg_lon,
            o_ep={
                "kind": "network_node",
                "network": "bmrcl",
                "node_id": "station:nadaprabhu_kempegowda",
                "lat": float(m["latitude"]),
                "lon": float(m["longitude"]),
                "display_name": m["name"],
            },
            d_ep={
                "kind": "network_node",
                "network": "bmrcl",
                "node_id": "station:mg_road",
                "lat": mg_lat,
                "lon": mg_lon,
                "display_name": mg_name,
            },
            invoke_live_traffic=False,
        )
    )

    # Root-cause synthesis for OD1
    od1 = report["ods"][0]
    report["synthesis"] = _synthesize(od1, report["expected_direct_metro"])

    OUT.write_text(json.dumps(report, indent=2, default=str))
    _print_summary(report)
    print(f"\nWrote {OUT}")


def _synthesize(od1: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    ep_o = (od1.get("orchestrator") or {}).get("endpoint_origin") or {}
    ep_d = (od1.get("orchestrator") or {}).get("endpoint_destination") or {}
    jb = od1.get("journey_builder_direct") or {}
    lt = od1.get("loss_trace") or {}
    att = od1.get("attiguppe_metro_candidates") or []
    access = od1.get("access_station_distances_from_origin") or []
    majestic = next((a for a in access if a["id"] == "nadaprabhu_kempegowda"), None)
    attiguppe = next((a for a in access if a["id"] == "attaluru"), None)

    why_attiguppe = []
    if att:
        why_attiguppe.append(
            "Attiguppe appears as first metro boarding on one or more retained candidates."
        )
        if attiguppe and majestic:
            if attiguppe["distance_m"] > majestic["distance_m"]:
                why_attiguppe.append(
                    f"Origin is CLOSER to Majestic metro ({majestic['distance_m']}m) "
                    f"than Attiguppe ({attiguppe['distance_m']}m) — Attiguppe is NOT nearer."
                )
            why_attiguppe.append(
                "Road access radius is 5000m; Attiguppe is within road-access range, "
                "so auto/cab→Attiguppe→metro is topologically allowed."
            )
            why_attiguppe.append(
                "Search collects many road-access metro boardings; diversity/signature "
                "caps retain some far boardings alongside nearer ones."
            )

    return {
        "endpoint_origin_kind": ep_o.get("kind"),
        "endpoint_destination_kind": ep_d.get("kind"),
        "endpoint_origin_node_id": ep_o.get("node_id"),
        "endpoint_destination_node_id": ep_d.get("node_id"),
        "walk_metro_walk_generated": jb.get("walk_metro_walk_generated"),
        "pure_metro_generated": jb.get("pure_metro_generated"),
        "loss_trace": lt,
        "attiguppe_count": len(att),
        "why_attiguppe": why_attiguppe,
        "majestic_access_m": majestic,
        "attiguppe_access_m": attiguppe,
        "expected": {
            "hops": expected["metro_hops_stations_travelled"],
            "fare": expected["fare_inr"],
            "duration_min": expected["structural_duration_min"],
        },
    }


def _print_summary(report: Dict[str, Any]) -> None:
    print("=== Phase 7K-7 Diagnostic Summary ===")
    exp = report["expected_direct_metro"]
    print(
        f"Network direct: {exp['origin_station']['id']} → purple → "
        f"{exp['destination_station']['id']} hops={exp['metro_hops_stations_travelled']} "
        f"fare=₹{exp['fare_inr']} dur≈{exp['structural_duration_min']}min"
    )
    syn = report["synthesis"]
    print(f"OD1 endpoint kinds: origin={syn['endpoint_origin_kind']} dest={syn['endpoint_destination_kind']}")
    print(f"OD1 node IDs: {syn['endpoint_origin_node_id']} → {syn['endpoint_destination_node_id']}")
    print(f"JB walk→metro→walk: {syn['walk_metro_walk_generated']}  pure metro: {syn['pure_metro_generated']}")
    print(f"Loss hint: {(syn.get('loss_trace') or {}).get('problem_layer_hint')}")
    print(f"Attiguppe metro candidates: {syn['attiguppe_count']}")
    for line in syn.get("why_attiguppe") or []:
        print(f"  - {line}")
    for od in report["ods"]:
        g = od.get("generality_flags") or {}
        print(
            f"{od['label']}: direct={g.get('direct_metro_generated')} "
            f"wmw={g.get('walk_metro_walk_generated')} "
            f"attiguppe={g.get('attiguppe_detour_present')} "
            f"suspicious={g.get('suspicious_road_combos_present')} "
            f"metro_DE={g.get('metro_reaches_decision_engine')}"
        )
        de = (od.get("decision_engine_inputs") or {}).get("categories") or {}
        if de:
            print(
                f"  CHEAPEST={(de.get('CHEAPEST') or {}).get('sig')} "
                f"FASTEST={(de.get('FASTEST') or {}).get('sig')} "
                f"BEST={(de.get('BEST_OVERALL') or {}).get('sig')}"
            )


if __name__ == "__main__":
    main()
