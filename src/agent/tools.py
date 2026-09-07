"""
ADK-compatible tools wrapping existing application services.

Public ADK tool signatures use only Python-3.9-safe primitives so
FunctionTool declaration succeeds. Internal APIs remain strongly typed.
"""

from __future__ import annotations

import json
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


def _empty_to_none(value: str) -> Optional[str]:
    text = (value or "").strip()
    return text if text else None


def _nonneg_or_none(value: float) -> Optional[float]:
    if value is None:
        return None
    if float(value) < 0:
        return None
    return float(value)


def _zone_or_none(value: int) -> Optional[int]:
    if value is None or int(value) < 0:
        return None
    return int(value)


def _parse_modes_csv(modes_csv: str) -> Optional[List[str]]:
    text = (modes_csv or "").strip()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts or None


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
    departure_time: str = "",
    objective: str = "",
    origin_zone: int = -1,
    destination_zone: int = -1,
    avoid_heavy_traffic: bool = False,
    max_walking_minutes: float = -1.0,
    max_cost: float = -1.0,
    modes_csv: str = "",
) -> dict:
    """Plan a commute using the deterministic planner. Ranking is not done by Gemini.

    Optional values use empty strings / -1 sentinels (ADK/Python 3.9 safe).
    modes_csv is a comma-separated list such as "DRIVE,TRANSIT".
    """
    preferences = UserPreferences(
        avoid_heavy_traffic=bool(avoid_heavy_traffic),
        max_walking_minutes=_nonneg_or_none(max_walking_minutes),
        max_cost=_nonneg_or_none(max_cost),
    )
    request = CommuteRequest(
        user_id=user_id,
        origin=origin,
        destination=destination,
        departure_time=_empty_to_none(departure_time),
        objective=_empty_to_none(objective),
        preferences=preferences,
        origin_zone=_zone_or_none(origin_zone),
        destination_zone=_zone_or_none(destination_zone),
        modes=_parse_modes_csv(modes_csv),
    )
    result = _plan_commute(request)
    payload = result.to_dict()
    payload["tool"] = "plan_commute"
    return payload


def get_routes(
    origin: str,
    destination: str,
    departure_time: str = "",
    modes_csv: str = "",
) -> dict:
    """Fetch candidate routes from the existing Maps mobility service.

    modes_csv is a comma-separated list such as "DRIVE,TRANSIT,WALK".
    """
    travel_modes = _to_travel_modes(_parse_modes_csv(modes_csv))
    candidates = _get_candidate_routes(
        origin=origin,
        destination=destination,
        departure_time=_empty_to_none(departure_time),
        modes=travel_modes,
    )
    return {
        "tool": "get_routes",
        "routes": [c.to_dict() for c in candidates],
        "count": len(candidates),
    }


def get_user_preferences(user_id: str) -> dict:
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
) -> dict:
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
    candidates_json: str,
    time_weight: float = 1.0,
    cost_weight: float = 1.0,
    walking_weight: float = 1.0,
    transfer_weight: float = 1.0,
    congestion_weight: float = 1.0,
    reliability_weight: float = 1.0,
    avoid_heavy_traffic: bool = False,
    max_walking_minutes: float = -1.0,
    max_cost: float = -1.0,
    preferred_modes_csv: str = "",
) -> dict:
    """Rank candidate routes with the deterministic evaluation engine.

    candidates_json: JSON array of route candidate objects.
    preferred_modes_csv: comma-separated mode names.
    """
    raw = json.loads(candidates_json) if candidates_json else []
    if not isinstance(raw, list):
        raise ValueError("candidates_json must be a JSON array of route objects")
    routes = [_candidate_from_dict(item) for item in raw]
    preferences = UserPreferences(
        time_weight=float(time_weight),
        cost_weight=float(cost_weight),
        walking_weight=float(walking_weight),
        transfer_weight=float(transfer_weight),
        congestion_weight=float(congestion_weight),
        reliability_weight=float(reliability_weight),
        preferred_modes=_parse_modes_csv(preferred_modes_csv),
        max_walking_minutes=_nonneg_or_none(max_walking_minutes),
        max_cost=_nonneg_or_none(max_cost),
        avoid_heavy_traffic=bool(avoid_heavy_traffic),
    )
    result = _evaluate_routes(routes, preferences)
    payload = result.to_dict()
    payload["tool"] = "evaluate_routes"
    return payload


def get_weather(location: str) -> dict:
    """Weather context. Not configured — does not fabricate conditions."""
    payload = _not_configured("weather")
    payload["location"] = location
    return payload


def get_disruptions(origin: str, destination: str) -> dict:
    """Live disruption feed. Not configured — does not fabricate incidents."""
    payload = _not_configured("disruptions")
    payload["origin"] = origin
    payload["destination"] = destination
    return payload


def get_commute_history(user_id: str) -> dict:
    """User commute history. Not configured — does not fabricate trips."""
    payload = _not_configured("commute_history")
    payload["user_id"] = user_id
    payload["trips"] = []
    return payload


def save_feedback(
    user_id: str,
    route_id: str,
    rating: int = -1,
    comment: str = "",
) -> dict:
    """Persist commute feedback. Not configured — does not pretend to save.

    rating=-1 means unset; comment="" means unset.
    """
    payload = _not_configured("feedback")
    payload["user_id"] = user_id
    payload["route_id"] = route_id
    payload["accepted"] = False
    payload["rating"] = None if int(rating) < 0 else int(rating)
    payload["comment"] = _empty_to_none(comment)
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
