"""
Validation helpers for normalized static mobility payloads.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from src.network.models import (
    FareRule,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
    MobilityStopTime,
    MobilityTrip,
)


def _valid_coord(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def validate_network_payload(payload: Dict[str, Any]) -> List[str]:
    """
    Validate a normalized snapshot payload.

    Expected optional keys:
      stops, stations, routes, fare_rules, trips, stop_times,
      shapes, calendars, agencies (lists of dicts).

    At least one of stops/stations/routes/fare_rules must be non-empty.
    """
    errors: List[str] = []
    if not isinstance(payload, dict):
        return ["PAYLOAD_NOT_OBJECT"]

    stops_raw = payload.get("stops") or []
    stations_raw = payload.get("stations") or []
    routes_raw = payload.get("routes") or []
    fares_raw = payload.get("fare_rules") or []
    trips_raw = payload.get("trips") or []
    stop_times_raw = payload.get("stop_times") or []

    if not any([stops_raw, stations_raw, routes_raw, fares_raw]):
        errors.append("EMPTY_DATASET (no stops/stations/routes/fare_rules)")

    stop_ids: Set[str] = set()
    station_ids: Set[str] = set()
    route_ids: Set[str] = set()
    fare_ids: Set[str] = set()
    trip_ids: Set[str] = set()

    for i, raw in enumerate(stops_raw):
        try:
            stop = MobilityStop.from_dict(raw)
        except Exception as exc:
            errors.append(f"STOP_PARSE_ERROR[{i}] ({exc})")
            continue
        if stop.id in stop_ids:
            errors.append(f"DUPLICATE_STOP_ID ({stop.id})")
        stop_ids.add(stop.id)
        if not stop.name.strip():
            errors.append(f"STOP_MISSING_NAME ({stop.id})")
        if not _valid_coord(stop.latitude, stop.longitude):
            errors.append(f"STOP_INVALID_COORDINATES ({stop.id})")
        if stop.provenance is None or not stop.provenance.source:
            errors.append(f"STOP_MISSING_PROVENANCE ({stop.id})")

    for i, raw in enumerate(stations_raw):
        try:
            station = MobilityStation.from_dict(raw)
        except Exception as exc:
            errors.append(f"STATION_PARSE_ERROR[{i}] ({exc})")
            continue
        if station.id in station_ids:
            errors.append(f"DUPLICATE_STATION_ID ({station.id})")
        station_ids.add(station.id)
        # Coordinates optional when official source does not publish them.
        if station.latitude is not None or station.longitude is not None:
            if station.latitude is None or station.longitude is None:
                errors.append(f"STATION_PARTIAL_COORDINATES ({station.id})")
            elif not _valid_coord(station.latitude, station.longitude):
                errors.append(f"STATION_INVALID_COORDINATES ({station.id})")
        if not station.provenance.source:
            errors.append(f"STATION_MISSING_PROVENANCE ({station.id})")

    for i, raw in enumerate(routes_raw):
        try:
            route = MobilityRoute.from_dict(raw)
        except Exception as exc:
            errors.append(f"ROUTE_PARSE_ERROR[{i}] ({exc})")
            continue
        if route.id in route_ids:
            errors.append(f"DUPLICATE_ROUTE_ID ({route.id})")
        route_ids.add(route.id)
        if not route.provenance.source:
            errors.append(f"ROUTE_MISSING_PROVENANCE ({route.id})")
        for sid in route.stop_ids:
            if stop_ids and sid not in stop_ids and sid not in station_ids:
                errors.append(
                    f"ROUTE_STOP_REF_UNRESOLVED ({route.id} → {sid})"
                )

    for i, raw in enumerate(fares_raw):
        try:
            rule = FareRule.from_dict(raw)
        except Exception as exc:
            errors.append(f"FARE_PARSE_ERROR[{i}] ({exc})")
            continue
        if rule.id in fare_ids:
            errors.append(f"DUPLICATE_FARE_ID ({rule.id})")
        fare_ids.add(rule.id)
        if not rule.provenance.source:
            errors.append(f"FARE_MISSING_PROVENANCE ({rule.id})")
        if rule.effective_from and rule.effective_until:
            if rule.effective_until < rule.effective_from:
                errors.append(f"FARE_INVALID_EFFECTIVE_WINDOW ({rule.id})")

    for i, raw in enumerate(trips_raw):
        try:
            trip = MobilityTrip.from_dict(raw)
        except Exception as exc:
            errors.append(f"TRIP_PARSE_ERROR[{i}] ({exc})")
            continue
        if trip.id in trip_ids:
            errors.append(f"DUPLICATE_TRIP_ID ({trip.id})")
        trip_ids.add(trip.id)
        if route_ids and trip.route_id not in route_ids:
            errors.append(f"TRIP_ROUTE_REF_UNRESOLVED ({trip.id} → {trip.route_id})")
        if not trip.provenance.source:
            errors.append(f"TRIP_MISSING_PROVENANCE ({trip.id})")

    for i, raw in enumerate(stop_times_raw):
        try:
            st = MobilityStopTime.from_dict(raw)
        except Exception as exc:
            errors.append(f"STOP_TIME_PARSE_ERROR[{i}] ({exc})")
            continue
        if trip_ids and st.trip_id not in trip_ids:
            errors.append(
                f"STOP_TIME_TRIP_REF_UNRESOLVED ({st.trip_id})"
            )
        if stop_ids and st.stop_id not in stop_ids and st.stop_id not in station_ids:
            errors.append(
                f"STOP_TIME_STOP_REF_UNRESOLVED ({st.stop_id})"
            )
        # Explicitly forbid fabricated midnight defaults marked as missing.
        if raw.get("arrival_time_fabricated") or raw.get("departure_time_fabricated"):
            errors.append(f"STOP_TIME_FABRICATED_FLAG ({st.trip_id}:{st.stop_sequence})")

    for raw in stations_raw:
        try:
            station = MobilityStation.from_dict(raw)
        except Exception:
            continue
        for other in station.interchange_station_ids:
            if station_ids and other not in station_ids:
                errors.append(
                    f"STATION_INTERCHANGE_UNRESOLVED ({station.id} → {other})"
                )

    return errors


def assert_no_hardcoded_journeys(module_globals: Dict[str, Any]) -> None:
    """Test helper: reject accidental ALLOWED_JOURNEYS-style constants."""
    forbidden_names = {
        "ALLOWED_JOURNEYS",
        "HARDCODED_JOURNEYS",
        "FIXED_JOURNEY_COMBINATIONS",
        "CANONICAL_JOURNEYS",
    }
    for name in forbidden_names:
        if name in module_globals:
            raise AssertionError(
                f"Hardcoded journey constant {name} must not exist"
            )
