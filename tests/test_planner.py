"""
Unit tests for the commute planning orchestrator.

Maps HTTP is mocked. Tests do not require a live API key.
"""

from unittest.mock import patch

import pytest

from src.decision_engine.models import RouteCandidate, UserPreferences
from src.decision_engine.evaluator import evaluate_routes
from src.mobility.maps_client import MapsAPIError
from src.planner import CommuteRequest, plan_commute, InvalidCommuteRequest


def _candidate(**overrides) -> RouteCandidate:
    defaults = dict(
        route_id="maps_drive_0",
        mode="cab",
        travel_time_minutes=32.0,
        cost=350.0,
        walking_minutes=2.0,
        transfers=0,
        congestion_score=0.75,
        reliability_score=0.70,
        disruption_risk=0.15,
        historical_mobility_signal=None,
    )
    defaults.update(overrides)
    return RouteCandidate(**defaults)


def _cheap_transit() -> RouteCandidate:
    return _candidate(
        route_id="maps_transit_0",
        mode="metro",
        travel_time_minutes=55.0,
        cost=25.0,
        walking_minutes=5.0,
        transfers=1,
        congestion_score=0.15,
        reliability_score=0.85,
        disruption_risk=0.08,
    )


def _base_request(**overrides) -> CommuteRequest:
    defaults = dict(
        user_id="user-1",
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        departure_time="2024-09-06T08:00:00Z",
        objective="fastest",
        preferences=UserPreferences(),
    )
    defaults.update(overrides)
    return CommuteRequest(**defaults)


HISTORICAL_SIGNAL = {
    "signal_source": "historical_uber_movement_ml",
    "has_historical_coverage": True,
    "origin_zone": 12,
    "destination_zone": 84,
    "hour": 8,
    "historical_typical_travel_time_minutes": 33.5,
    "historical_congestion_factor": 1.05,
}


# =============================================================================
# 1. Basic commute planning
# =============================================================================

@patch("src.planner.service.get_candidate_routes")
def test_basic_commute_planning(mock_maps):
    mock_maps.return_value = [_candidate(), _cheap_transit()]
    result = plan_commute(_base_request())

    assert result.error is None
    assert len(result.routes) == 2
    assert result.evaluation is not None
    assert result.evaluation.recommended_route is not None
    assert result.evaluation.ranked_routes
    assert result.historical_signal_used is False


# =============================================================================
# 2. Planner calls mobility service
# =============================================================================

@patch("src.planner.service.get_candidate_routes")
def test_planner_calls_mobility_service(mock_maps):
    mock_maps.return_value = [_candidate()]
    request = _base_request(modes=["DRIVE", "TRANSIT"])
    plan_commute(request)

    mock_maps.assert_called_once()
    kwargs = mock_maps.call_args.kwargs
    assert kwargs["origin"] == request.origin
    assert kwargs["destination"] == request.destination
    assert kwargs["departure_time"] == request.departure_time
    assert [m.value for m in kwargs["modes"]] == ["DRIVE", "TRANSIT"]


# =============================================================================
# 3. Planner calls evaluator
# =============================================================================

@patch("src.planner.service.evaluate_routes")
@patch("src.planner.service.get_candidate_routes")
def test_planner_calls_evaluator(mock_maps, mock_eval):
    candidates = [_candidate(), _cheap_transit()]
    mock_maps.return_value = candidates
    mock_eval.return_value = evaluate_routes(candidates, UserPreferences())

    prefs = UserPreferences(time_weight=8.0)
    plan_commute(_base_request(preferences=prefs))

    mock_eval.assert_called_once()
    called_routes, called_prefs = mock_eval.call_args.args
    assert called_routes == candidates
    assert called_prefs.time_weight == 8.0


# =============================================================================
# 4. Preference changes change recommendation
# =============================================================================

@patch("src.planner.service.get_candidate_routes")
def test_preference_changes_change_recommendation(mock_maps):
    mock_maps.return_value = [_candidate(), _cheap_transit()]

    time_sensitive = plan_commute(_base_request(
        preferences=UserPreferences(time_weight=10.0, cost_weight=0.5)
    ))
    cost_sensitive = plan_commute(_base_request(
        preferences=UserPreferences(time_weight=0.5, cost_weight=10.0)
    ))

    rec_a = time_sensitive.evaluation.recommended_route.route_id
    rec_b = cost_sensitive.evaluation.recommended_route.route_id
    assert rec_a == "maps_drive_0"
    assert rec_b == "maps_transit_0"
    assert rec_a != rec_b


# =============================================================================
# 5. No historical IDs → no ML claim
# =============================================================================

@patch("src.planner.service.get_historical_mobility_signal")
@patch("src.planner.service.get_candidate_routes")
def test_no_historical_ids_does_not_claim_ml(mock_maps, mock_ml):
    mock_maps.return_value = [_candidate()]
    result = plan_commute(_base_request())

    mock_ml.assert_not_called()
    assert result.historical_signal_used is False
    assert "uber_movement_xgboost" not in result.data_sources
    assert result.data_sources == ["google_maps_routes"]
    assert result.routes[0].historical_mobility_signal is None


# =============================================================================
# 6. Explicit historical IDs → historical tool invoked
# =============================================================================

@patch("src.planner.service.get_historical_mobility_signal")
@patch("src.planner.service.get_candidate_routes")
def test_explicit_historical_ids_invoke_ml(mock_maps, mock_ml):
    mock_maps.return_value = [_candidate()]
    mock_ml.return_value = HISTORICAL_SIGNAL

    result = plan_commute(_base_request(origin_zone=12, destination_zone=84))

    mock_ml.assert_called_once()
    kwargs = mock_ml.call_args.kwargs
    assert kwargs["origin_zone"] == 12
    assert kwargs["destination_zone"] == 84
    assert kwargs["hour"] == 8
    assert result.historical_signal_used is True
    assert result.routes[0].historical_mobility_signal == HISTORICAL_SIGNAL
    assert result.data_sources == ["google_maps_routes", "uber_movement_xgboost"]


@patch("src.planner.service.get_historical_mobility_signal")
@patch("src.planner.service.get_candidate_routes")
def test_incomplete_zones_do_not_invoke_ml(mock_maps, mock_ml):
    mock_maps.return_value = [_candidate()]
    result = plan_commute(_base_request(origin_zone=12))

    mock_ml.assert_not_called()
    assert result.historical_signal_used is False
    assert "uber_movement_xgboost" not in result.data_sources
    assert any("HISTORICAL_ZONES_INCOMPLETE" in w for w in result.warnings)


# =============================================================================
# 7. No routes
# =============================================================================

@patch("src.planner.service.get_historical_mobility_signal")
@patch("src.planner.service.get_candidate_routes")
def test_no_routes(mock_maps, mock_ml):
    mock_maps.return_value = []
    result = plan_commute(_base_request())

    mock_ml.assert_not_called()
    assert result.routes == []
    assert result.evaluation is None
    assert result.error == "NO_ROUTES"
    assert "NO_ROUTES" in result.warnings
    assert result.data_sources == ["google_maps_routes"]
    assert result.historical_signal_used is False


# =============================================================================
# 8. Maps failure
# =============================================================================

@patch("src.planner.service.get_candidate_routes")
def test_maps_failure(mock_maps):
    mock_maps.side_effect = MapsAPIError("Maps API returned HTTP 500.", 500)
    result = plan_commute(_base_request())

    assert result.error == "MAPS_API_UNAVAILABLE"
    assert result.evaluation is None
    assert result.routes == []
    assert result.historical_signal_used is False
    assert "google_maps_routes" not in result.data_sources
    assert "uber_movement_xgboost" not in result.data_sources


# =============================================================================
# 9. Deterministic result
# =============================================================================

@patch("src.planner.service.get_candidate_routes")
def test_deterministic_result(mock_maps):
    mock_maps.return_value = [_candidate(), _cheap_transit()]
    request = _base_request(preferences=UserPreferences(time_weight=2.0, cost_weight=1.5))

    result_1 = plan_commute(request)
    result_2 = plan_commute(request)

    assert result_1.to_dict() == result_2.to_dict()


# =============================================================================
# 10. data_sources accurately reflects what happened
# =============================================================================

@patch("src.planner.service.get_historical_mobility_signal")
@patch("src.planner.service.get_candidate_routes")
def test_data_sources_maps_only_when_ml_unavailable(mock_maps, mock_ml):
    mock_maps.return_value = [_candidate()]
    mock_ml.side_effect = FileNotFoundError("no artifacts")

    result = plan_commute(_base_request(origin_zone=12, destination_zone=84))

    mock_ml.assert_called_once()
    assert result.historical_signal_used is False
    assert result.data_sources == ["google_maps_routes"]
    assert "HISTORICAL_MODEL_UNAVAILABLE" in result.warnings
    assert "uber_movement_xgboost" not in result.data_sources


@patch("src.planner.service.get_candidate_routes")
def test_invalid_request_raises(mock_maps):
    with pytest.raises(InvalidCommuteRequest):
        plan_commute(_base_request(origin=""))
    mock_maps.assert_not_called()


@patch("src.planner.service.evaluate_routes")
@patch("src.planner.service.get_candidate_routes")
def test_evaluator_failure(mock_maps, mock_eval):
    mock_maps.return_value = [_candidate()]
    mock_eval.side_effect = RuntimeError("boom")

    result = plan_commute(_base_request())

    assert result.error == "EVALUATOR_FAILURE"
    assert result.evaluation is None
    assert len(result.routes) == 1
    assert result.data_sources == ["google_maps_routes"]


@patch("src.planner.service.get_candidate_routes")
def test_malformed_mobility_response(mock_maps):
    mock_maps.return_value = ["not-a-candidate"]
    result = plan_commute(_base_request())

    assert result.error == "MALFORMED_MOBILITY_RESPONSE"
    assert result.evaluation is None
    assert result.historical_signal_used is False
