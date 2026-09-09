"""
Pydantic request schemas for the HTTP API (Python 3.9 compatible).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class PreferencesIn(BaseModel):
    time_weight: float = 1.0
    cost_weight: float = 1.0
    walking_weight: float = 1.0
    transfer_weight: float = 1.0
    congestion_weight: float = 1.0
    reliability_weight: float = 1.0
    preferred_modes: Optional[List[str]] = None
    excluded_modes: Optional[List[str]] = None
    max_walking_minutes: Optional[float] = None
    max_cost: Optional[float] = None
    avoid_heavy_traffic: bool = False


class PlanRequest(BaseModel):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)
    departure_time: Optional[str] = None
    objective: Optional[str] = None
    # Named Decision Engine profile (FASTEST / CHEAPEST / …); overrides objective map.
    preference_profile: Optional[str] = None
    user_id: str = "api-user"
    origin_zone: Optional[int] = None
    destination_zone: Optional[int] = None
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None
    modes: Optional[List[str]] = None
    preferences: Optional[PreferencesIn] = None
    invoke_gemini: bool = True
    invoke_weather: bool = True
    invoke_historical: bool = True
    # None → service default (True for live API). Tests/smoke set False explicitly.
    invoke_live_traffic: Optional[bool] = None
    allow_legacy_maps_fallback: bool = True

    @field_validator("origin", "destination")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ContextChangeIn(BaseModel):
    traffic_changed: bool = False
    disruption_changed: bool = False
    weather_changed: bool = False
    updated_departure_time: Optional[str] = None
    context_source: str = "none"
    target_route_id: Optional[str] = None
    congestion_delta: float = 0.0
    travel_time_delta_minutes: float = 0.0
    disruption_delta: float = 0.0
    weather_note: Optional[str] = None
    description: str = ""

    @field_validator("context_source")
    @classmethod
    def _source_ok(cls, value: str) -> str:
        allowed = {"none", "live", "simulated"}
        if value not in allowed:
            raise ValueError(f"context_source must be one of {sorted(allowed)}")
        return value


class ReplanRequest(BaseModel):
    """Replan using the same commute request fields + a context change.

    If initial planner snapshot fields are omitted, /replan plans first, then replans.
    """
    request: PlanRequest
    context_change: ContextChangeIn
    refresh_live_routes: bool = False
    invoke_gemini: bool = True
