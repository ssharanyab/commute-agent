#!/usr/bin/env python3
"""Phase 7K-4 diagnostic: anchored vs place endpoints (no scoring changes)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.agent.demo_od import MAJESTIC
from src.journey_builder import DynamicJourneyBuilder, JourneyBuildRequest, JourneyEndpoint
from src.journey_builder.builder import ORIGIN_ID, DEST_ID
from src.network.file_repository import FileStaticMobilityRepository


def _station(repo, sid: str):
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stations") or []:
            if str(raw.get("id")) == sid:
                return float(raw["latitude"]), float(raw["longitude"]), str(raw.get("name"))
    raise KeyError(sid)


def _stop_near(repo, lat: float, lon: float):
    from src.journey_builder.graph import haversine_m, stop_node_id

    best = None
    for payload in repo._all_active_payloads():  # noqa: SLF001
        for raw in payload.get("stops") or []:
            if raw.get("latitude") is None:
                continue
            d = haversine_m(lat, lon, float(raw["latitude"]), float(raw["longitude"]))
            if best is None or d < best[0]:
                best = (d, str(raw["id"]), float(raw["latitude"]), float(raw["longitude"]))
    return best


def _report(label, result, o_ep, d_ep):
    print("\n" + "=" * 72)
    print(label)
    print(f"  origin_endpoint: {o_ep.to_dict() if o_ep else None}")
    print(f"  dest_endpoint:   {d_ep.to_dict() if d_ep else None}")
    sigs = sorted({j.mode_signature for j in result.candidates})
    print(f"  signatures ({len(result.candidates)}): {sigs[:12]}")
    zero = []
    for j in result.candidates:
        for leg in j.legs:
            dist = float(leg.distance_meters or 0)
            if dist > 0.5:
                continue
            if leg.from_node_id == ORIGIN_ID:
                zero.append((j.mode_signature, leg.mode.value, leg.to_node_id, "access"))
            if leg.to_node_id == DEST_ID:
                zero.append((j.mode_signature, leg.mode.value, leg.from_node_id, "egress"))
    print(f"  zero-distance access/egress legs: {zero[:8] or 'NONE'}")
    # Prefer metro-containing then first
    pick = None
    for j in result.candidates:
        if "metro" in j.modes:
            pick = j
            break
    if pick is None and result.candidates:
        pick = result.candidates[0]
    if pick:
        print(f"  sample journey: {pick.mode_signature}")
        print(
            "  legs:",
            [
                f"{l.mode.value}:{l.from_node_id}->{l.to_node_id}"
                f"({None if l.distance_meters is None else round(float(l.distance_meters),1)}m)"
                for l in pick.legs
            ],
        )


def main():
    repo = FileStaticMobilityRepository(Path("data/mobility_network"))
    builder = DynamicJourneyBuilder(repo)
    dep = datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc)
    maj = _station(repo, "nadaprabhu_kempegowda")
    mg = _station(repo, "mg_road")
    ind = _station(repo, "indiranagar")
    mg_area = (12.9754, 77.6065)

    cases = []

    o1 = JourneyEndpoint.network_node(
        network="bmrcl", node_id="station:nadaprabhu_kempegowda", lat=maj[0], lon=maj[1]
    )
    d1 = JourneyEndpoint.network_node(
        network="bmrcl", node_id="station:mg_road", lat=mg[0], lon=mg[1]
    )
    cases.append(("1. Majestic Metro → MG Road Metro (anchored)", o1, d1, maj[0], maj[1], mg[0], mg[1]))

    o2 = JourneyEndpoint.network_node(
        network="bmrcl", node_id="station:mg_road", lat=mg[0], lon=mg[1]
    )
    d2 = JourneyEndpoint.network_node(
        network="bmrcl", node_id="station:indiranagar", lat=ind[0], lon=ind[1]
    )
    cases.append(("2. MG Road Metro → Indiranagar Metro", o2, d2, mg[0], mg[1], ind[0], ind[1]))

    o3 = o1
    d3 = JourneyEndpoint.place(lat=mg_area[0], lon=mg_area[1], display_name="MG Road")
    cases.append(("3. Majestic Metro → MG Road (place)", o3, d3, maj[0], maj[1], mg_area[0], mg_area[1]))

    o4 = JourneyEndpoint.place(lat=MAJESTIC.latitude, lon=MAJESTIC.longitude, display_name="Majestic")
    d4 = d3
    cases.append(
        (
            "4. Majestic → MG Road (places)",
            o4,
            d4,
            MAJESTIC.latitude,
            MAJESTIC.longitude,
            mg_area[0],
            mg_area[1],
        )
    )

    near = _stop_near(repo, maj[0], maj[1])
    near2 = _stop_near(repo, mg[0], mg[1])
    if near and near2 and near[1] != near2[1]:
        o5 = JourneyEndpoint.network_node(
            network="bmtc", node_id=f"stop:{near[1]}", lat=near[2], lon=near[3]
        )
        d5 = JourneyEndpoint.network_node(
            network="bmtc", node_id=f"stop:{near2[1]}", lat=near2[2], lon=near2[3]
        )
        cases.append(
            (
                f"5. BMTC stop {near[1]} → {near2[1]}",
                o5,
                d5,
                near[2],
                near[3],
                near2[2],
                near2[3],
            )
        )

    for label, o_ep, d_ep, ola, olo, dla, dlo in cases:
        result = builder.build(
            JourneyBuildRequest(
                origin_lat=ola,
                origin_lon=olo,
                destination_lat=dla,
                destination_lon=dlo,
                departure_time=dep,
                origin_endpoint=o_ep,
                destination_endpoint=d_ep,
            )
        )
        _report(label, result, o_ep, d_ep)


if __name__ == "__main__":
    main()
