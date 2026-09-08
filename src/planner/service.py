"""
Commute planner service.

Orchestrates existing mobility and decision-engine modules. Does not
duplicate Maps API logic or scoring.
"""

from dataclasses import replace
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

from src.planner.models import CommuteRequest, PlannerResult, InvalidCommuteRequest
from src.mobility.models import TravelMode
from src.mobility.service import get_candidate_routes
from src.mobility.maps_client import MapsAPIError, MissingAPIKeyError, NoRoutesFoundError
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.predict import get_historical_mobility_signal
from src.historical_signal import compute_deviation_percent, classify_deviation


SOURCE_GOOGLE_MAPS = "google_maps_routes"
SOURCE_UBER_XGBOOST = "uber_movement_xgboost"

_MODE_ALIASES = {
    "drive": TravelMode.DRIVE,
    "driving": TravelMode.DRIVE,
    "cab": TravelMode.DRIVE,
    "car": TravelMode.DRIVE,
    "rideshare": TravelMode.DRIVE,
    "transit": TravelMode.TRANSIT,
    "metro": TravelMode.TRANSIT,
    "bus": TravelMode.TRANSIT,
    "public": TravelMode.TRANSIT,
    "walk": TravelMode.WALK,
    "walking": TravelMode.WALK,
}


def _validate_request(request: CommuteRequest) -> None:
    if request is None:
        raise InvalidCommuteRequest("CommuteRequest is required.")
    if not isinstance(request.user_id, str) or not request.user_id.strip():
        raise InvalidCommuteRequest("user_id is required.")
    if not isinstance(request.origin, str) or not request.origin.strip():
        raise InvalidCommuteRequest("origin is required.")
    if not isinstance(request.destination, str) or not request.destination.strip():
        raise InvalidCommuteRequest("destination is required.")


def _convert_modes(request: CommuteRequest, warnings: List[str]) -> List[TravelMode]:
    if not request.modes:
        return [TravelMode.DRIVE, TravelMode.TRANSIT]

    converted: List[TravelMode] = []
    seen = set()
    for raw in request.modes:
        if isinstance(raw, TravelMode):
            mode = raw
        elif isinstance(raw, str) and raw.strip():
            key = raw.strip().lower()
            mode = _MODE_ALIASES.get(key)
            if mode is None:
                warnings.append(f"UNKNOWN_TRAVEL_MODE ({raw})")
                continue
        else:
            warnings.append(f"UNKNOWN_TRAVEL_MODE ({raw})")
            continue
        if mode not in seen:
            converted.append(mode)
            seen.add(mode)

    if not converted:
        raise InvalidCommuteRequest("No valid travel modes were provided.")
    return converted


def _hour_from_departure(departure_time: Optional[str], warnings: List[str]) -> int:
    if not departure_time:
        return datetime.now(timezone.utc).hour
    try:
        normalized = departure_time.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).hour
    except (TypeError, ValueError):
        warnings.append(f"INVALID_DEPARTURE_TIME ({departure_time}); using current UTC hour")
        return datetime.now(timezone.utc).hour


def _explicit_zones(request: CommuteRequest, warnings: List[str]) -> Optional[Tuple[int, int]]:
    origin_set = request.origin_zone is not None
    dest_set = request.destination_zone is not None
    if origin_set ^ dest_set:
        warnings.append("HISTORICAL_ZONES_INCOMPLETE; both origin_zone and destination_zone are required")
        return None
    if not origin_set:
        return None
    try:
        origin_zone = int(request.origin_zone)
        destination_zone = int(request.destination_zone)
    except (TypeError, ValueError):
        warnings.append("HISTORICAL_ZONES_INVALID")
        return None
    if origin_zone < 0 or destination_zone < 0:
        warnings.append("HISTORICAL_ZONES_INVALID")
        return None
    return origin_zone, destination_zone


def _attach_historical_signal(
    routes: List[RouteCandidate],
    request: CommuteRequest,
    warnings: List[str],
    models_dir: str,
) -> Tuple[List[RouteCandidate], Optional[Dict[str, Any]], bool]:
    """Attach XGBoost signal only when both zone IDs are explicit.

    Returns (routes, signal_or_none, historical_signal_used).
    """
    zones = _explicit_zones(request, warnings)
    if zones is None:
        return routes, None, False

    origin_zone, destination_zone = zones
    hour = _hour_from_departure(request.departure_time, warnings)
    try:
        signal = get_historical_mobility_signal(
            origin_zone=origin_zone,
            destination_zone=destination_zone,
            hour=hour,
            models_dir=models_dir,
        )
    except FileNotFoundError:
        warnings.append("HISTORICAL_MODEL_UNAVAILABLE")
        return routes, None, False
    except ValueError as e:
        warnings.append(f"HISTORICAL_SIGNAL_INVALID_INPUT ({e})")
        return routes, None, False
    except Exception as e:
        warnings.append(f"HISTORICAL_SIGNAL_FAILED ({type(e).__name__})")
        return routes, None, False

    if not isinstance(signal, dict):
        warnings.append("HISTORICAL_SIGNAL_MALFORMED")
        return routes, None, False

    # Per-route copy: Maps duration remains authoritative; attach deviation vs historical.
    attached: List[RouteCandidate] = []
    for route in routes:
        sig = dict(signal)
        if sig.get("has_historical_coverage") is True:
            hist_expected = sig.get("historical_expected_travel_time_minutes")
            if hist_expected is None:
                hist_expected = sig.get("historical_typical_travel_time_minutes")
            sig["current_minutes"] = route.travel_time_minutes
            dev = compute_deviation_percent(route.travel_time_minutes, hist_expected)
            sig["deviation_percent"] = dev
            sig["deviation_state"] = classify_deviation(dev)
        attached.append(replace(route, historical_mobility_signal=sig))

    if not signal.get("has_historical_coverage"):
        warnings.append("HISTORICAL_COVERAGE_MISSING")
    return attached, signal, True


def _empty_result(
    request: CommuteRequest,
    warnings: List[str],
    data_sources: List[str],
    error: Optional[str] = None,
    error_detail: Optional[str] = None,
    routes: Optional[List[RouteCandidate]] = None,
    historical_signal_used: bool = False,
) -> PlannerResult:
    return PlannerResult(
        request=request,
        routes=routes or [],
        evaluation=None,
        data_sources=data_sources,
        historical_signal_used=historical_signal_used,
        warnings=warnings,
        error=error,
        error_detail=error_detail,
    )


def plan_commute(
    request: CommuteRequest,
    api_key: Optional[str] = None,
    models_dir: str = "models",
    cache_ttl: Optional[int] = None,
) -> PlannerResult:
    """Plan a commute by orchestrating Maps candidates, optional ML, and evaluation.

    Args:
        request: Validated commute request.
        api_key: Optional Maps API key override (tests/demo only).
        models_dir: Directory of XGBoost artifacts, used only when zone IDs are set.
        cache_ttl: Optional Maps cache TTL override.

    Returns:
        PlannerResult with candidates, evaluation, data_sources, and warnings.

    Raises:
        InvalidCommuteRequest: If required request fields are missing or invalid.
    """
    warnings: List[str] = []
    _validate_request(request)
    modes = _convert_modes(request, warnings)
    data_sources: List[str] = []

    fetch_kwargs: Dict[str, Any] = {
        "origin": request.origin.strip(),
        "destination": request.destination.strip(),
        "departure_time": request.departure_time,
        "modes": modes,
        "api_key": api_key,
    }
    if cache_ttl is not None:
        fetch_kwargs["cache_ttl"] = cache_ttl

    try:
        candidates = get_candidate_routes(**fetch_kwargs)
    except MissingAPIKeyError as e:
        return _empty_result(
            request, warnings, data_sources,
            error="MAPS_API_UNAVAILABLE",
            error_detail=str(e),
        )
    except NoRoutesFoundError as e:
        return _empty_result(
            request, warnings, data_sources,
            error="NO_ROUTES",
            error_detail=str(e),
        )
    except MapsAPIError as e:
        return _empty_result(
            request, warnings, data_sources,
            error="MAPS_API_UNAVAILABLE",
            error_detail=str(e),
        )
    except Exception as e:
        return _empty_result(
            request, warnings, data_sources,
            error="MAPS_API_UNAVAILABLE",
            error_detail=f"{type(e).__name__}: {e}",
        )

    if candidates is None:
        warnings.append("MALFORMED_MOBILITY_RESPONSE")
        return _empty_result(
            request, warnings, data_sources,
            error="MALFORMED_MOBILITY_RESPONSE",
            error_detail="get_candidate_routes returned None",
        )

    if not isinstance(candidates, list):
        warnings.append("MALFORMED_MOBILITY_RESPONSE")
        return _empty_result(
            request, warnings, data_sources,
            error="MALFORMED_MOBILITY_RESPONSE",
            error_detail=f"Expected list of RouteCandidate, got {type(candidates).__name__}",
        )

    for item in candidates:
        if not isinstance(item, RouteCandidate):
            warnings.append("MALFORMED_MOBILITY_RESPONSE")
            return _empty_result(
                request, warnings, data_sources,
                error="MALFORMED_MOBILITY_RESPONSE",
                error_detail="Mobility response contained a non-RouteCandidate item",
            )

    routes: List[RouteCandidate] = list(candidates)
    data_sources.append(SOURCE_GOOGLE_MAPS)
    if not routes:
        warnings.append("NO_ROUTES")
        return _empty_result(
            request,
            warnings,
            data_sources,
            error="NO_ROUTES",
            error_detail="Maps returned no candidate routes",
            routes=routes,
            historical_signal_used=False,
        )

    routes, _, historical_used = _attach_historical_signal(
        routes, request, warnings, models_dir
    )
    if historical_used:
        data_sources.append(SOURCE_UBER_XGBOOST)

    preferences = request.preferences if request.preferences is not None else UserPreferences()

    try:
        evaluation = evaluate_routes(routes, preferences)
    except Exception as e:
        warnings.append("EVALUATOR_FAILURE")
        return PlannerResult(
            request=request,
            routes=routes,
            evaluation=None,
            data_sources=data_sources,
            historical_signal_used=historical_used,
            warnings=warnings,
            error="EVALUATOR_FAILURE",
            error_detail=f"{type(e).__name__}: {e}",
        )

    if evaluation.recommended_route is None and routes:
        warnings.append("NO_VALID_ROUTES_UNDER_CONSTRAINTS")
        return PlannerResult(
            request=request,
            routes=routes,
            evaluation=evaluation,
            data_sources=data_sources,
            historical_signal_used=historical_used,
            warnings=warnings,
            error="NO_VALID_ROUTES",
            error_detail=(
                "All candidate routes violate hard user constraints "
                "(e.g. excluded modes, max walking, max cost)."
            ),
        )

    return PlannerResult(
        request=request,
        routes=routes,
        evaluation=evaluation,
        data_sources=data_sources,
        historical_signal_used=historical_used,
        warnings=warnings,
    )
