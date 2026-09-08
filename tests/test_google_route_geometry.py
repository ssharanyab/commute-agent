"""
Phase 3: Google Routes API polyline / route-token preservation tests.

Uses mocked Maps responses — no live API key required.
"""

from __future__ import annotations

from unittest.mock import patch

from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import RouteCandidate, UserPreferences, preference_profile, PROFILE_FASTEST
from src.mobility.maps_client import FIELD_MASK, TRANSIT_FIELD_MASK
from src.mobility.models import MapsRouteRequest, TravelMode
from src.mobility.route_adapter import adapt_maps_response, field_provenance
from src.mobility.service import _clear_cache
from src.planner.models import CommuteRequest
from src.planner.service import plan_commute
from tests.maps_fixtures import (
    POLYLINE_DRIVE_MAIN,
    POLYLINE_DRIVE_ALT,
    ROUTE_TOKEN_DRIVE_MAIN,
    ROUTE_TOKEN_DRIVE_ALT,
    get_drive_route_fixture,
    get_drive_route_missing_geometry_fixture,
    get_drive_alternative_routes_fixture,
    get_transit_route_fixture,
)
from tests.test_mobility import make_client, mock_post
from tests.fixtures import get_bengaluru_test_candidates


def test_field_mask_requests_polyline_and_route_token():
    assert "routes.polyline.encodedPolyline" in FIELD_MASK
    assert "routes.routeToken" in FIELD_MASK
    assert "routes.polyline.encodedPolyline" in TRANSIT_FIELD_MASK
    assert "routes.routeToken" in TRANSIT_FIELD_MASK


def test_google_encoded_polyline_parsed():
    client = make_client()
    with patch("requests.post", return_value=mock_post(get_drive_route_fixture())):
        routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.DRIVE)
        )
    assert len(routes) == 1
    assert routes[0].encoded_polyline == POLYLINE_DRIVE_MAIN


def test_google_route_token_parsed_when_present():
    client = make_client()
    with patch("requests.post", return_value=mock_post(get_drive_route_fixture())):
        routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.DRIVE)
        )
    assert routes[0].route_token == ROUTE_TOKEN_DRIVE_MAIN


def test_missing_polyline_handled_safely():
    client = make_client()
    with patch(
        "requests.post",
        return_value=mock_post(get_drive_route_missing_geometry_fixture()),
    ):
        routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.DRIVE)
        )
    assert routes[0].encoded_polyline is None
    candidate = adapt_maps_response(routes[0])
    assert candidate.google_polyline is None


def test_missing_route_token_handled_safely():
    client = make_client()
    with patch("requests.post", return_value=mock_post(get_transit_route_fixture())):
        routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.TRANSIT)
        )
    assert routes[0].encoded_polyline is not None
    assert routes[0].route_token is None
    candidate = adapt_maps_response(routes[0])
    assert candidate.google_route_token is None


def test_polyline_token_stay_with_correct_route_after_evaluation():
    client = make_client()
    with patch(
        "requests.post",
        return_value=mock_post(get_drive_alternative_routes_fixture()),
    ):
        maps_routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.DRIVE, compute_alternatives=True)
        )
    candidates = [adapt_maps_response(r) for r in maps_routes]
    assert candidates[0].google_polyline == POLYLINE_DRIVE_MAIN
    assert candidates[0].google_route_token == ROUTE_TOKEN_DRIVE_MAIN
    assert candidates[1].google_polyline == POLYLINE_DRIVE_ALT
    assert candidates[1].google_route_token == ROUTE_TOKEN_DRIVE_ALT

    # Prefer checking attachment survives ranking reorder
    res = evaluate_routes(candidates, UserPreferences())
    by_id = {sr.route.route_id: sr.route for sr in res.ranked_routes}
    assert by_id["maps_drive_0"].google_polyline == POLYLINE_DRIVE_MAIN
    assert by_id["maps_drive_0"].google_route_token == ROUTE_TOKEN_DRIVE_MAIN
    assert by_id["maps_drive_1"].google_polyline == POLYLINE_DRIVE_ALT
    assert by_id["maps_drive_1"].google_route_token == ROUTE_TOKEN_DRIVE_ALT


def test_selected_recommendation_exposes_correct_polyline_and_token():
    client = make_client()
    with patch(
        "requests.post",
        return_value=mock_post(get_drive_alternative_routes_fixture()),
    ):
        maps_routes = client.compute_routes(
            MapsRouteRequest("A", "B", mode=TravelMode.DRIVE, compute_alternatives=True)
        )
    candidates = [adapt_maps_response(r) for r in maps_routes]
    # FASTEST → maps_drive_0 (shorter duration)
    res = evaluate_routes(candidates, preference_profile(PROFILE_FASTEST))
    assert res.recommended_route is not None
    assert res.recommended_route.route_id == "maps_drive_0"
    assert res.recommended_route.google_polyline == POLYLINE_DRIVE_MAIN
    assert res.recommended_route.google_route_token == ROUTE_TOKEN_DRIVE_MAIN


def test_fixture_routes_work_without_polyline_token():
    candidates = get_bengaluru_test_candidates()
    for c in candidates:
        assert c.google_polyline is None
        assert c.google_route_token is None
    res = evaluate_routes(candidates, UserPreferences())
    assert res.recommended_route is not None
    assert res.recommended_route.google_polyline is None
    assert res.recommended_route.google_route_token is None


def test_provenance_marks_geometry_live_and_cost_heuristic():
    prov = field_provenance(TravelMode.DRIVE)
    assert prov["google_polyline"] == "live"
    assert prov["google_route_token"] == "live"
    assert prov["travel_time_minutes"] == "live"
    assert prov["distance_meters"] == "live"
    assert prov["cost"] == "heuristic"
    assert prov["congestion_score"] == "heuristic"


def test_maps_errors_unchanged_with_geometry_field_mask():
    from src.mobility.maps_client import MapsAPIError, NoRoutesFoundError

    client = make_client()
    with patch("requests.post", return_value=mock_post({"routes": []}, status_code=200)):
        try:
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))
            raised = False
        except NoRoutesFoundError:
            raised = True
    assert raised

    with patch("requests.post", return_value=mock_post({}, status_code=403)):
        try:
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))
            auth_raised = False
        except MapsAPIError as e:
            auth_raised = True
            assert e.status_code == 403
    assert auth_raised


def test_planner_preserves_geometry_on_recommendation():
    _clear_cache()

    def _fake_candidates(**kwargs):
        return [
            RouteCandidate(
                route_id="maps_drive_0",
                mode="cab",
                travel_time_minutes=32.0,
                cost=350.0,
                walking_minutes=0.0,
                transfers=0,
                congestion_score=0.4,
                reliability_score=0.7,
                disruption_risk=0.1,
                google_polyline=POLYLINE_DRIVE_MAIN,
                google_route_token=ROUTE_TOKEN_DRIVE_MAIN,
                distance_meters=18500,
            ),
            RouteCandidate(
                route_id="maps_drive_1",
                mode="cab",
                travel_time_minutes=48.0,
                cost=280.0,
                walking_minutes=0.0,
                transfers=0,
                congestion_score=0.3,
                reliability_score=0.75,
                disruption_risk=0.1,
                google_polyline=POLYLINE_DRIVE_ALT,
                google_route_token=ROUTE_TOKEN_DRIVE_ALT,
                distance_meters=21000,
            ),
        ]

    with patch("src.planner.service.get_candidate_routes", side_effect=_fake_candidates):
        result = plan_commute(
            CommuteRequest(
                user_id="u1",
                origin="Electronic City, Bengaluru",
                destination="Koramangala, Bengaluru",
                preferences=preference_profile(PROFILE_FASTEST),
            )
        )
    assert result.error is None
    assert result.evaluation is not None
    rec = result.evaluation.recommended_route
    assert rec is not None
    assert rec.route_id == "maps_drive_0"
    assert rec.google_polyline == POLYLINE_DRIVE_MAIN
    assert rec.google_route_token == ROUTE_TOKEN_DRIVE_MAIN
    # Serialization exposes fields additively
    payload = rec.to_dict()
    assert payload["google_polyline"] == POLYLINE_DRIVE_MAIN
    assert payload["google_route_token"] == ROUTE_TOKEN_DRIVE_MAIN
