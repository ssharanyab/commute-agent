"""
Phase 7H — Location resolution diagnosis tests (updated for Phase 7I).

Historically labels resolved only via landmark table. Phase 7I adds Google
Geocoding; these tests pin stage attribution and offline landmark behavior
with allow_google=False where needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.agent.demo_od import BENGALURU_LANDMARKS, ELECTRONIC_CITY, MAJESTIC
from src.agent.orchestrator import (
    MobilityOrchestrator,
    OrchestratorRequest,
    resolve_coordinates,
)
from src.api.schemas import PlanRequest
from src.api.service import _resolve_landmark_coords, orchestrator_request_from_plan

REPRO_MATRIX = [
    ("Electronic City", "Majestic"),
    ("Indiranagar", "Majestic"),
    ("Jayanagar", "Majestic"),
    ("Silk Board", "Indiranagar"),
    ("Koramangala", "Indiranagar"),
    ("Whitefield", "Majestic"),
    ("HSR Layout", "Koramangala"),
]


def test_landmark_table_contains_demo_and_common_anchors():
    keys = set(BENGALURU_LANDMARKS)
    assert "electronic city" in keys
    assert "majestic" in keys
    assert "indiranagar" in keys
    assert "koramangala" in keys
    assert "koramangala phase 5" not in keys


def test_electronic_city_majestic_resolve_via_landmark_table():
    o_lat, o_lon, o_how = resolve_coordinates(
        "Electronic City", None, None, allow_google=False
    )
    d_lat, d_lon, d_how = resolve_coordinates(
        "Majestic", None, None, allow_google=False
    )
    assert o_how == d_how == "landmark_table"
    assert o_lat == pytest.approx(ELECTRONIC_CITY.latitude)
    assert d_lat == pytest.approx(MAJESTIC.latitude)


def test_explicit_coords_bypass_landmark_table():
    lat, lon, how = resolve_coordinates("Anything", 12.97, 77.59)
    assert how == "explicit"
    assert lat == pytest.approx(12.97)


def test_case_and_suffix_variants_for_demo_anchors():
    assert (
        resolve_coordinates(
            "electronic city, bengaluru", None, None, allow_google=False
        )[2]
        == "landmark_table"
    )
    assert resolve_coordinates("MAJESTIC", None, None, allow_google=False)[2] == (
        "landmark_table"
    )
    assert (
        resolve_coordinates(
            "Electronic City Phase 1", None, None, allow_google=False
        )[2]
        == "unresolved"
    )


@pytest.mark.parametrize("origin,destination", REPRO_MATRIX)
def test_repro_matrix_resolves_offline(origin, destination):
    o_how = resolve_coordinates(origin, None, None, allow_google=False)[2]
    d_how = resolve_coordinates(destination, None, None, allow_google=False)[2]
    assert o_how == "landmark_table"
    assert d_how == "landmark_table"


def test_unknown_label_unresolved_without_google():
    lat, lon, how = resolve_coordinates(
        "Completely Fake Place 12345", None, None, allow_google=False
    )
    assert how == "unresolved"
    assert lat is None


def test_api_adapter_uses_same_landmark_table():
    assert _resolve_landmark_coords("Completely Fake") == (None, None)
    assert _resolve_landmark_coords("Electronic City") == (
        ELECTRONIC_CITY.latitude,
        ELECTRONIC_CITY.longitude,
    )
    req = orchestrator_request_from_plan(
        PlanRequest(origin="Indiranagar", destination="Majestic")
    )
    assert req.origin_lat == pytest.approx(12.9784)
    assert req.destination_lat == pytest.approx(MAJESTIC.latitude)


def test_orchestrator_fails_at_geocode_stage_not_journey_builder():
    orch = MobilityOrchestrator(repository=None)
    with patch("src.mobility.geocoding.geocode_bengaluru", return_value=None):
        result = orch.run(
            OrchestratorRequest(
                user_id="diag",
                origin="Completely Fake Place 12345",
                destination="Also Fake Destination 67890",
                departure_time=datetime(2030, 1, 15, 8, 0, tzinfo=timezone.utc),
                invoke_gemini=False,
                invoke_live_traffic=False,
                invoke_weather=False,
                invoke_historical=False,
                allow_legacy_maps_fallback=False,
            )
        )
    assert result.recommendation.error == "COORDINATES_UNRESOLVED"
    assert result.journeys == []
    assert result.journey_build is None
    geocode = next(c for c in result.metadata.capabilities if c.name == "geocode")
    assert geocode.status == "failed"
    assert not any(c.name == "journey_builder" for c in result.metadata.capabilities)


def test_failure_is_geocoding_not_anchoring_when_labels_unknown():
    o_lat, _, o_how = resolve_coordinates(
        "Completely Fake Place 12345", None, None, allow_google=False
    )
    d_lat, _, d_how = resolve_coordinates(
        "Majestic", None, None, allow_google=False
    )
    assert o_how == "unresolved" and o_lat is None
    assert d_how == "landmark_table" and d_lat is not None


def test_with_explicit_coords_geocode_stage_passes():
    orch = MobilityOrchestrator(repository=None)
    result = orch.run(
        OrchestratorRequest(
            user_id="diag",
            origin="Koramangala",
            destination="Indiranagar",
            departure_time=datetime(2030, 1, 15, 8, 0, tzinfo=timezone.utc),
            origin_lat=12.9352,
            origin_lon=77.6245,
            destination_lat=12.9784,
            destination_lon=77.6408,
            invoke_gemini=False,
            invoke_live_traffic=False,
            invoke_weather=False,
            invoke_historical=False,
            allow_legacy_maps_fallback=False,
        )
    )
    assert result.recommendation.error != "COORDINATES_UNRESOLVED"
    geocode = next(c for c in result.metadata.capabilities if c.name == "geocode")
    assert geocode.status == "invoked"
    assert geocode.detail.get("origin") == "explicit"
