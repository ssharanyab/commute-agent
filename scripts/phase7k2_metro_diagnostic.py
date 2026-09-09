#!/usr/bin/env python3
"""Phase 7K-2 diagnostic: Metro candidate economics + DE ranks (no scoring changes)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.capabilities.adapt import journeys_to_route_candidates
from src.agent.demo_od import BENGALURU_LANDMARKS, MAJESTIC
from src.decision_engine import evaluate_routes, preference_profile
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest
from src.journey_builder.models import ValueStatus
from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import MobilityMode


def _station_coords(repo: FileStaticMobilityRepository, station_id: str) -> Tuple[float, float]:
    for payload in repo._all_active_payloads():  # noqa: SLF001 — diagnostic only
        for raw in payload.get("stations") or []:
            if str(raw.get("id")) == station_id:
                return float(raw["latitude"]), float(raw["longitude"])
    raise KeyError(station_id)


def _landmark(name: str):
    key = name.strip().lower()
    if key in BENGALURU_LANDMARKS:
        return BENGALURU_LANDMARKS[key]
    if key == "majestic":
        return MAJESTIC
    raise KeyError(name)


def _mg_road_area() -> Tuple[str, float, float]:
    # Area label near MG Road (not station pin) — ~300m walk typical.
    return "MG Road (area)", 12.9754, 77.6065


def _pick_metro(journeys) -> Optional[Any]:
    walk_metro_walk = []
    any_metro = []
    for j in journeys:
        modes = [l.mode.value for l in j.legs]
        any_metro.append(j) if MobilityMode.METRO.value in modes else None
        if modes == ["walk", "metro", "walk"]:
            walk_metro_walk.append(j)
        elif "metro" in modes and "walk" in modes:
            any_metro.append(j)
    if walk_metro_walk:
        return walk_metro_walk[0]
    metros = [j for j in journeys if any(l.mode == MobilityMode.METRO for l in j.legs)]
    return metros[0] if metros else None


def _station_sequence(j) -> List[str]:
    seq: List[str] = []
    for leg in j.legs:
        if leg.mode == MobilityMode.METRO:
            if not seq and leg.from_ref:
                seq.append(str(leg.from_ref))
            if leg.to_ref:
                seq.append(str(leg.to_ref))
    return seq


def _print_metro(label: str, j) -> None:
    print(f"\n=== {label} ===")
    if j is None:
        print("NO METRO CANDIDATE")
        return
    print(f"candidate_id: {j.candidate_id}")
    print(f"mode_signature: {j.mode_signature}")
    print(
        "legs:",
        " → ".join(
            f"{l.mode.value}({l.from_ref or l.from_name}->{l.to_ref or l.to_name})"
            for l in j.legs
        ),
    )
    print(f"station_sequence: {_station_sequence(j)}")
    dur = j.total_duration_seconds
    print(
        f"duration: {None if dur is None else round(dur / 60.0, 2)} min "
        f"(seconds={dur})"
    )
    print(f"duration_status: {j.duration_status}")
    # Per-leg structural metro estimate (journey aggregate stays unknown).
    metro_secs = sum(
        float(l.duration_seconds or 0.0)
        for l in j.legs
        if l.mode == MobilityMode.METRO and l.duration_seconds is not None
    )
    print(
        f"metro_leg_duration_seconds_sum: {metro_secs or None} "
        f"(structural estimate; status unknown)"
    )
    print(f"cost: {j.total_cost_inr}")
    print(f"cost_status: {j.cost_status}")
    print(f"walking_distance_m: {j.walking_distance_meters}")
    print(f"transfers: {j.transfer_count}")
    print(f"provenance_sources: {j.provenance_sources}")
    print(f"snapshot_versions: {j.snapshot_versions}")
    for leg in j.legs:
        if leg.mode == MobilityMode.METRO:
            print(
                "  metro_leg:",
                {
                    "cost_inr": leg.cost_inr,
                    "cost_status": leg.cost_status,
                    "duration_seconds": leg.duration_seconds,
                    "duration_status": leg.duration_status,
                    "distance_meters": leg.distance_meters,
                    "cost_meta": (leg.metadata or {}).get("cost_meta"),
                    "duration_meta": (leg.metadata or {}).get("duration_meta"),
                },
            )


def _classify(c) -> str:
    modes = [m.lower() for m in (c.component_modes or [c.mode])]
    if "metro" in modes:
        return "metro"
    if "bus" in modes:
        return "bmtc"
    if "auto_rickshaw" in modes or c.mode in {"auto_rickshaw", "auto"}:
        return "auto"
    if "cab" in modes or c.mode == "cab":
        return "cab"
    return c.mode or "other"


def _rank_report(tag: str, candidates, profile: str) -> Dict[str, Any]:
    prefs = preference_profile(profile)
    result = evaluate_routes(candidates, preferences=prefs)
    ranked = [sr for sr in result.ranked_routes if sr.is_valid]
    rows = []
    best = {}
    for i, sr in enumerate(ranked, start=1):
        kind = _classify(sr.route)
        rows.append(
            {
                "rank": i,
                "kind": kind,
                "route_id": sr.route.route_id,
                "score": round(sr.final_score, 4),
                "cost": sr.route.cost,
                "cost_status": sr.route.cost_status,
                "time_min": sr.route.travel_time_minutes,
                "duration_status": sr.route.duration_status,
                "modes": sr.route.component_modes or [sr.route.mode],
            }
        )
        if kind not in best:
            best[kind] = rows[-1]
    winner = rows[0] if rows else None
    print(f"\n-- {tag} / {profile} --")
    for kind in ("metro", "auto", "bmtc", "cab"):
        b = best.get(kind)
        if b:
            print(
                f"  {kind}: rank={b['rank']} score={b['score']} "
                f"cost={b['cost']}({b['cost_status']}) "
                f"time={b['time_min']}({b['duration_status']})"
            )
        else:
            print(f"  {kind}: (absent)")
    if winner:
        print(f"  winner: {winner['kind']} {winner['route_id']} score={winner['score']}")
    return {"best": best, "winner": winner, "n": len(rows)}


def _strip_metro_enrichment(journeys):
    """Simulate pre-7K-2: no hop distance → no structural metro duration seconds."""
    from dataclasses import replace

    out = []
    for j in journeys:
        new_legs = []
        for leg in j.legs:
            if leg.mode == MobilityMode.METRO:
                meta = dict(leg.metadata or {})
                meta.pop("duration_meta", None)
                leg = replace(
                    leg,
                    distance_meters=None,
                    duration_seconds=None,
                    duration_status=ValueStatus.UNKNOWN.value,
                    metadata=meta,
                )
            new_legs.append(leg)
        out.append(
            replace(
                j,
                legs=new_legs,
                total_duration_seconds=None,
                duration_status=ValueStatus.UNKNOWN.value,
            )
        )
    return out


def _legacy_adapt_before(journeys):
    """Apply HEAD adapt fabrication (8 min metro when dist missing) for BEFORE ranks."""
    import src.agent.capabilities.adapt as adapt

    orig = adapt._leg_duration_minutes

    def _before(leg, enrichment):
        minutes, status = orig(leg, enrichment)
        if leg.mode.value == "metro" and (
            leg.distance_meters is None or float(leg.distance_meters or 0) <= 0
        ):
            if leg.duration_seconds is None:
                return 8.0, ValueStatus.UNKNOWN.value
        return minutes, status

    adapt._leg_duration_minutes = _before
    try:
        return journeys_to_route_candidates(journeys)
    finally:
        adapt._leg_duration_minutes = orig


def main() -> None:
    repo = FileStaticMobilityRepository(Path("data/mobility_network"))
    builder = DynamicJourneyBuilder(repo)
    departure = datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc)

    majestic = _landmark("majestic")
    indira = _landmark("indiranagar")
    mg_name, mg_lat, mg_lon = _mg_road_area()
    maj_st = _station_coords(repo, "nadaprabhu_kempegowda")
    mg_st = _station_coords(repo, "mg_road")

    ods = [
        ("A Majestic → MG Road", majestic.latitude, majestic.longitude, mg_lat, mg_lon),
        (
            "B Majestic Metro → MG Road Metro",
            maj_st[0],
            maj_st[1],
            mg_st[0],
            mg_st[1],
        ),
        (
            "C Majestic → Indiranagar",
            majestic.latitude,
            majestic.longitude,
            indira.latitude,
            indira.longitude,
        ),
        (
            "D MG Road → Indiranagar",
            mg_lat,
            mg_lon,
            indira.latitude,
            indira.longitude,
        ),
    ]

    print("Published BMRCL fare_rules count:", len(repo.get_fare_rules() or []))

    for label, ola, olo, dla, dlo in ods:
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=ola,
                origin_lon=olo,
                destination_lat=dla,
                destination_lon=dlo,
                departure_time=departure,
            )
        )
        metro = _pick_metro(result.candidates)
        _print_metro(label, metro)

        after_cands = journeys_to_route_candidates(result.candidates)
        before_journeys = _strip_metro_enrichment(result.candidates)
        before_cands = _legacy_adapt_before(before_journeys)

        for profile in ("CHEAPEST", "FASTEST", "BALANCED"):
            _rank_report("BEFORE transit enrichment", before_cands, profile)
            _rank_report("AFTER transit enrichment", after_cands, profile)


if __name__ == "__main__":
    main()
