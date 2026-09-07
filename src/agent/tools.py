"""
ADK-compatible tools wrapping existing application services.

These functions are the tool surface. They do not reimplement Maps, ML,
or scoring — they call the existing modules.
"""

from typing import Any, Dict, List, Optional

from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes as _evaluate_routes
from src.mobility.models import TravelMode
from src.mobility.service import get_candidate_routes as _get_candidate_routes
from src.planner.models import CommuteRequest
from src.planner.service import plan_commute as _plan_commute
from src.predict import get_historical_mobility_signal as _get_historical_mobility_signal


def _not_configured(service: str) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": "not_configured",
        "service": service,
    }


def _to_travel_modes(modes: Optional[List[str]]) -> Optional[List[TravelMode]]:
    if not modes:
        return None
    aliases = {
        "drive": TravelMode.DRIVE,
        "driving": TravelMode.DRIVE,
        "cab": TravelMode.DRIVE,
        "car": TravelMode.DRIVE,
        "transit": TravelMode.TRANSIT,
        "metro": TravelMode.TRANSIT,
        "bus": TravelMode.TRANSIT,
        "walk": TravelMode.WALK,
        "walking": TravelMode.WALK,
    }
    converted = []
    seen = set()
    for raw in modes:
        if isinstance(raw, TravelMode):
            mode = raw
        else:
            mode = aliases.get(str(raw).strip().lower())
        if mode and mode not in seen:
            converted.append(mode)
            seen.add(mode)
    return converted or None


def _candidate_from_dict(payload: Dict[str, Any]) -> RouteCandidate:
    return RouteCandidate(
        route_id=str(payload["route_id"]),
        mode=str(payload.get("mode", "cab")),
        travel_time_minutes=float(payload.get("travel_time_minutes", 0.0)),
        cost=float(payload.get("cost", 0.0)),
        walking_minutes=float(payload.get("walking_minutes", 0.0)),
        transfers=int(payload.get("transfers", 0)),
        congestion_score=float(payload.get("congestion_score", 0.0)),
        reliability_score=float(payload.get("reliability_score", 0.0)),
        disruption_risk=float(payload.get("disruption_risk", 0.0)),
        historical_mobility_signal=payload.get("historical_mobility_signal"),
    )


def plan_commute(
    user_id: str,
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
    objective: Optional[str] = None,
    origin_zone: Optional[int] = None,
    destination_zone: Optional[int] = None,
    avoid_heavy_traffic: bool = False,
    max_walking_minutes: Optional[float] = None,
    max_cost: Optional[float] = None,
    modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Plan a commute using the deterministic planner. Ranking is not done by Gemini."""
    preferences = UserPreferences(
        avoid_heavy_traffic=bool(avoid_heavy_traffic),
        max_walking_minutes=max_walking_minutes,
        max_cost=max_cost,
    )
    request = CommuteRequest(
        user_id=user_id,
        origin=origin,
        destination=destination,
        departure_time=departure_time,
        objective=objective,
        preferences=preferences,
        origin_zone=origin_zone,
        destination_zone=destination_zone,
        modes=modes,
    )
    result = _plan_commute(request)
    payload = result.to_dict()
    payload["tool"] = "plan_commute"
    return payload


def get_routes(
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
    modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Fetch candidate routes from the existing Maps mobility service."""
    travel_modes = _to_travel_modes(modes)
    candidates = _get_candidate_routes(
        origin=origin,
        destination=destination,
        departure_time=departure_time,
        modes=travel_modes,
    )
    return {
        "tool": "get_routes",
        "routes": [c.to_dict() for c in candidates],
        "count": len(candidates),
    }


def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Load stored user preferences. Not configured in this checkpoint."""
    payload = _not_configured("user_preferences")
    payload["user_id"] = user_id
    payload["preferences"] = None
    return payload


def predict_historical_travel_time(
    origin_zone: int,
    destination_zone: int,
    hour: int,
    models_dir: str = "models",
) -> Dict[str, Any]:
    """Return the Uber Movement XGBoost historical signal for explicit ward IDs."""
    signal = _get_historical_mobility_signal(
        origin_zone=int(origin_zone),
        destination_zone=int(destination_zone),
        hour=int(hour),
        models_dir=models_dir,
    )
    payload = dict(signal)
    payload["tool"] = "predict_historical_travel_time"
    return payload


def evaluate_routes(
    candidates: List[Dict[str, Any]],
    time_weight: float = 1.0,
    cost_weight: float = 1.0,
    walking_weight: float = 1.0,
    transfer_weight: float = 1.0,
    congestion_weight: float = 1.0,
    reliability_weight: float = 1.0,
    avoid_heavy_traffic: bool = False,
    max_walking_minutes: Optional[float] = None,
    max_cost: Optional[float] = None,
    preferred_modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Rank candidate routes with the deterministic evaluation engine."""
    routes = [_candidate_from_dict(item) for item in candidates]
    preferences = UserPreferences(
        time_weight=time_weight,
        cost_weight=cost_weight,
        walking_weight=walking_weight,
        transfer_weight=transfer_weight,
        congestion_weight=congestion_weight,
        reliability_weight=reliability_weight,
        preferred_modes=preferred_modes,
        max_walking_minutes=max_walking_minutes,
        max_cost=max_cost,
        avoid_heavy_traffic=avoid_heavy_traffic,
    )
    result = _evaluate_routes(routes, preferences)
    payload = result.to_dict()
    payload["tool"] = "evaluate_routes"
    return payload


def get_weather(location: str) -> Dict[str, Any]:
    """Weather context. Not configured — does not fabricate conditions."""
    payload = _not_configured("weather")
    payload["location"] = location
    return payload


def get_disruptions(origin: str, destination: str) -> Dict[str, Any]:
    """Live disruption feed. Not configured — does not fabricate incidents."""
    payload = _not_configured("disruptions")
    payload["origin"] = origin
    payload["destination"] = destination
    return payload


def get_commute_history(user_id: str) -> Dict[str, Any]:
    """User commute history. Not configured — does not fabricate trips."""
    payload = _not_configured("commute_history")
    payload["user_id"] = user_id
    payload["trips"] = []
    return payload


def save_feedback(user_id: str, route_id: str, rating: Optional[int] = None, comment: Optional[str] = None) -> Dict[str, Any]:
    """Persist commute feedback. Not configured — does not pretend to save."""
    payload = _not_configured("feedback")
    payload["user_id"] = user_id
    payload["route_id"] = route_id
    payload["accepted"] = False
    payload["rating"] = rating
    payload["comment"] = comment
    return payload


def adk_tool_functions():
    """Return the callable tools for an ADK Agent tools= list."""
    return [
        plan_commute,
        get_routes,
        get_user_preferences,
        predict_historical_travel_time,
        evaluate_routes,
        get_weather,
        get_disruptions,
        get_commute_history,
        save_feedback,
    ]
