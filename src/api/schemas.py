"""
Pydantic request schemas for the HTTP API (Python 3.9 compatible).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from src.agent.mobility_strategy import (
    AccessoryMode,
    MobilityStrategy,
    normalize_excluded_mode_token,
)


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


class MobilityConstraintsIn(BaseModel):
    """Optional hard constraints (Phase 7A). Absent fields leave current behavior."""

    excluded_modes: Optional[List[str]] = None
    max_walking_distance_meters: Optional[float] = None
    max_transfers: Optional[int] = None
    allowed_accessory_modes: Optional[List[str]] = None

    @field_validator("max_walking_distance_meters")
    @classmethod
    def _walk_non_negative(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("max_walking_distance_meters must be >= 0")
        return value

    @field_validator("max_transfers")
    @classmethod
    def _transfers_non_negative(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("max_transfers must be >= 0")
        return value

    @field_validator("excluded_modes")
    @classmethod
    def _normalize_excluded(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        return [normalize_excluded_mode_token(m) for m in value]

    @field_validator("allowed_accessory_modes")
    @classmethod
    def _normalize_accessories(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        return [AccessoryMode.parse(m).value for m in value]


class EndpointIn(BaseModel):
    """Phase 7K-4 endpoint: place or published network node."""

    kind: str = "place"
    network: Optional[str] = None
    node_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    place_id: Optional[str] = None
    display_name: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _kind_ok(cls, value: str) -> str:
        key = (value or "place").strip().lower()
        if key not in {"place", "network_node"}:
            raise ValueError("kind must be 'place' or 'network_node'")
        return key


class PlanRequest(BaseModel):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)
    departure_time: Optional[str] = None
    objective: Optional[str] = None
    # Named Decision Engine profile (FASTEST / CHEAPEST / …); overrides objective map.
    preference_profile: Optional[str] = None
    # Phase 7A: journey composition strategy (not a preference profile).
    strategy: Optional[str] = None
    constraints: Optional[MobilityConstraintsIn] = None
    user_id: str = "api-user"
    origin_zone: Optional[int] = None
    destination_zone: Optional[int] = None
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None
    # Phase 7K-4 structured endpoints (optional; legacy lat/lon still work).
    origin_endpoint: Optional[EndpointIn] = None
    destination_endpoint: Optional[EndpointIn] = None
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

    @field_validator("strategy")
    @classmethod
    def _strategy_ok(cls, value: Optional[str]) -> Optional[str]:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return MobilityStrategy.parse(value).value


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
