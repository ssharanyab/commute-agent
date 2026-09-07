"""
Demo: ONE live Google Maps Routes API request.

Electronic City, Bengaluru → Koramangala, Bengaluru

Prints live Maps fields vs heuristic adapter fields.
Does not fabricate route data when Maps is unavailable.
"""

import os
from datetime import datetime, timezone, timedelta

from src.mobility.maps_client import (
    ROUTES_API_URL,
    MapsClient,
    MapsAPIError,
    MissingAPIKeyError,
    NoRoutesFoundError,
)
from src.mobility.models import MapsRouteRequest, TravelMode
from src.mobility.route_adapter import adapt_maps_response, field_provenance
from src.mobility.service import _clear_cache


ORIGIN = "Electronic City, Bengaluru"
DESTINATION = "Koramangala, Bengaluru"


def _banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def run_demo() -> None:
    _clear_cache()
    _banner("LIVE GOOGLE MAPS ROUTES — SINGLE REQUEST")
    print(f"  Endpoint: {ROUTES_API_URL}")
    print(f"  Origin:      {ORIGIN}")
    print(f"  Destination: {DESTINATION}")
    print(f"  Mode:        DRIVE (one request)")

    departure = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    print(f"  Departure:   {departure}")

    try:
        client = MapsClient()
    except MissingAPIKeyError as exc:
        print(f"\n  [BLOCKED] {exc}")
        print("  Set a real GOOGLE_MAPS_API_KEY in .env (not your_key_here).")
        print("  No fixtures were used. No route data was fabricated.")
        return

    request = MapsRouteRequest(
        origin=ORIGIN,
        destination=DESTINATION,
        mode=TravelMode.DRIVE,
        departure_time=departure,
        compute_alternatives=False,
    )

    try:
        routes = client.compute_routes(request)
    except NoRoutesFoundError as exc:
        print(f"\n  [NO ROUTES] {exc}")
        print("  No fixtures were used. No route data was fabricated.")
        return
    except MapsAPIError as exc:
        print(f"\n  [MAPS API ERROR] {exc}")
        print("  No fixtures were used. No route data was fabricated.")
        return

    print(f"\n  [LIVE] Received {len(routes)} route(s) from Google Maps Routes API.")
    provenance = field_provenance(TravelMode.DRIVE)

    for maps_route in routes:
        candidate = adapt_maps_response(maps_route)
        print("\n  --- Route ---")
        print(f"  route_id:     {candidate.route_id}")
        print(f"  mode:         {candidate.mode} (Maps travelMode={maps_route.mode.value})")
        print(
            f"  duration:     {candidate.travel_time_minutes} min "
            f"({maps_route.total_duration_seconds}s) "
            f"[{provenance['travel_time_minutes']}]"
        )
        print(
            f"  distance:     {maps_route.distance_meters} m "
            f"[{provenance['distance_meters']}]"
        )
        print(f"  description:  {maps_route.description or '-'}")
        print(f"  traffic_data: {maps_route.has_traffic_data} [live]")
        print(
            f"  cost (INR):   {candidate.cost} "
            f"[{provenance['cost']}]"
        )
        print(
            f"  congestion:   {candidate.congestion_score} "
            f"[{provenance['congestion_score']}]"
        )
        print(f"  data_source:  {provenance['data_source']}")
        print("  transit_info: n/a (DRIVE request)")

    print("\n  Provenance legend: live = Maps API field; heuristic = adapter estimate.")
    print()


if __name__ == "__main__":
    run_demo()
