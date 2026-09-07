"""
Unit tests for the Mobility layer.

Tests cover:
- API request construction
- DRIVE route parsing and conversion
- TRANSIT route parsing (legs, walking, transfers)
- WALK route parsing
- Handling alternative routes
- Missing optional fields in API response
- API errors (HTTP 401, 403, 429, non-200)
- Cache behavior (hit, miss, TTL)
- Missing API key
- No-route response
- RouteCandidate field validity from adapter
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from src.mobility.models import MapsRouteRequest, MapsRouteResponse, TravelMode
from src.mobility.maps_client import MapsClient, MissingAPIKeyError, MapsAPIError, NoRoutesFoundError
from src.mobility.route_adapter import adapt_drive_route, adapt_transit_route, adapt_walk_route, adapt_maps_response
from src.mobility.service import get_candidate_routes, _clear_cache, _cache_set, _cache_get
from src.decision_engine.models import RouteCandidate

from tests.maps_fixtures import (
    get_drive_route_fixture,
    get_drive_alternative_routes_fixture,
    get_transit_route_fixture,
    get_walk_route_fixture,
    get_empty_routes_fixture,
    get_no_routes_key_fixture,
)

# =============================================================================
# Helpers
# =============================================================================

def make_client(key: str = "FAKE_TEST_KEY_12345") -> MapsClient:
    """Build a MapsClient with a dummy key, bypassing env var check."""
    return MapsClient(api_key=key)


def mock_post(fixture: dict, status_code: int = 200):
    """Return a mock requests.post response."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = fixture
    return m


# =============================================================================
# 1. Missing API Key
# =============================================================================

def test_missing_api_key_raises():
    """MissingAPIKeyError raised when env var not set and no key passed."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
        with pytest.raises(MissingAPIKeyError):
            MapsClient()


def test_placeholder_api_key_raises():
    """MissingAPIKeyError raised when key equals placeholder value."""
    with pytest.raises(MissingAPIKeyError):
        MapsClient(api_key="your_key_here")


# =============================================================================
# 2. API Request Construction
# =============================================================================

def test_drive_request_body_includes_traffic_preference():
    """DRIVE requests must include routingPreference: TRAFFIC_AWARE."""
    client = make_client()
    req = MapsRouteRequest(
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        mode=TravelMode.DRIVE,
        departure_time="2030-01-01T08:00:00Z",
    )
    body = client._build_request_body(req)
    assert body["routingPreference"] == "TRAFFIC_AWARE"
    assert body["travelMode"] == "DRIVE"
    assert body["origin"] == {"address": "Electronic City, Bengaluru"}
    assert body["destination"] == {"address": "Koramangala, Bengaluru"}
    assert body["departureTime"] == "2030-01-01T08:00:00Z"
    assert "X-Goog-FieldMask" not in body


def test_transit_and_walk_request_bodies():
    """TRANSIT includes departureTime; WALK omits traffic preference."""
    client = make_client()
    transit = client._build_request_body(MapsRouteRequest(
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        mode=TravelMode.TRANSIT,
        departure_time="2030-01-01T08:00:00Z",
    ))
    assert transit["travelMode"] == "TRANSIT"
    assert transit["departureTime"] == "2030-01-01T08:00:00Z"
    assert "routingPreference" not in transit

    walk = client._build_request_body(MapsRouteRequest(
        origin="Electronic City, Bengaluru",
        destination="Koramangala, Bengaluru",
        mode=TravelMode.WALK,
    ))
    assert walk["travelMode"] == "WALK"
    assert "routingPreference" not in walk
    assert "departureTime" not in walk


def test_past_departure_time_clamped_for_drive():
    """Past departure times are clamped to a strictly future timestamp."""
    from src.mobility.maps_client import _normalize_departure_time
    from datetime import datetime, timezone, timedelta

    before = datetime.now(timezone.utc)
    clamped = _normalize_departure_time("2024-09-06T08:00:00Z")
    parsed = datetime.fromisoformat(clamped.replace("Z", "+00:00"))
    assert parsed > before
    assert parsed >= before + timedelta(seconds=55)


def test_empty_departure_time_clamped_to_future():
    """Empty departure is clamped to now + 60s (not exactly now)."""
    from src.mobility.maps_client import _normalize_departure_time
    from datetime import datetime, timezone, timedelta

    before = datetime.now(timezone.utc)
    clamped = _normalize_departure_time("")
    parsed = datetime.fromisoformat(clamped.replace("Z", "+00:00"))
    assert parsed > before
    assert parsed >= before + timedelta(seconds=55)


def test_naive_bengaluru_ist_departure_converted_to_utc():
    """Naive ISO is treated as Asia/Kolkata (IST), not UTC."""
    from src.mobility.maps_client import _normalize_departure_time

    # 14:00 IST = 08:30 UTC
    assert _normalize_departure_time("2030-01-15T14:00:00") == "2030-01-15T08:30:00Z"


def test_ist_offset_iso_converted_to_utc():
    """Explicit +05:30 offset converts to UTC for Maps."""
    from src.mobility.maps_client import _normalize_departure_time

    assert (
        _normalize_departure_time("2030-01-15T14:00:00+05:30")
        == "2030-01-15T08:30:00Z"
    )


def test_past_naive_ist_departure_clamped():
    """Past naive IST wall-clock is clamped to a future UTC timestamp."""
    from src.mobility.maps_client import _normalize_departure_time
    from datetime import datetime, timezone, timedelta

    before = datetime.now(timezone.utc)
    clamped = _normalize_departure_time("2020-01-01T09:00:00")
    parsed = datetime.fromisoformat(clamped.replace("Z", "+00:00"))
    assert parsed > before
    assert parsed >= before + timedelta(seconds=55)


def test_future_utc_departure_preserved():
    """Valid future UTC ISO is passed through as UTC Zulu."""
    from src.mobility.maps_client import _normalize_departure_time

    assert _normalize_departure_time("2030-06-01T10:00:00Z") == "2030-06-01T10:00:00Z"


def test_latlng_waypoint_parsing():
    """Lat/lng strings are converted to latLng waypoints, not address."""
    client = make_client()
    wp = client._build_waypoint("12.9716,77.5946")
    assert "location" in wp
    assert wp["location"]["latLng"]["latitude"] == pytest.approx(12.9716)
    assert wp["location"]["latLng"]["longitude"] == pytest.approx(77.5946)


def test_address_waypoint_parsing():
    """Non-coordinate strings are treated as address waypoints."""
    client = make_client()
    wp = client._build_waypoint("Koramangala, Bengaluru")
    assert "address" in wp
    assert "Koramangala" in wp["address"]


# =============================================================================
# 3. DRIVE Route Parsing
# =============================================================================

def test_drive_route_parsing():
    """Correctly parses DRIVE route duration, static duration, and traffic flag."""
    client = make_client()
    fixture = get_drive_route_fixture()

    with patch("requests.post", return_value=mock_post(fixture)):
        req = MapsRouteRequest("A", "B", mode=TravelMode.DRIVE)
        routes = client.compute_routes(req)

    assert len(routes) == 1
    r = routes[0]
    assert r.total_duration_seconds == 2280
    assert r.static_duration_seconds == 1800
    assert r.has_traffic_data is True
    assert r.distance_meters == 18500
    assert r.mode == TravelMode.DRIVE


def test_drive_route_to_route_candidate():
    """DRIVE MapsRouteResponse converts to RouteCandidate with correct fields."""
    resp = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.DRIVE,
        total_duration_seconds=2280,
        static_duration_seconds=1800,
        distance_meters=18500,
        has_traffic_data=True,
    )
    candidate = adapt_maps_response(resp)

    assert candidate.route_id == "maps_drive_0"
    assert candidate.mode == "cab"
    assert candidate.travel_time_minutes == pytest.approx(38.0)
    assert candidate.walking_minutes == 0.0
    assert candidate.transfers == 0
    assert 0.0 <= candidate.congestion_score <= 1.0
    assert 0.0 <= candidate.reliability_score <= 1.0
    assert candidate.cost > 0


# =============================================================================
# 4. TRANSIT Route Parsing
# =============================================================================

def test_transit_route_parsing():
    """Correctly parses TRANSIT route: duration, walking, transit legs, transfers."""
    client = make_client()
    fixture = get_transit_route_fixture()

    with patch("requests.post", return_value=mock_post(fixture)):
        req = MapsRouteRequest("A", "B", mode=TravelMode.TRANSIT)
        routes = client.compute_routes(req)

    assert len(routes) == 1
    r = routes[0]
    assert r.total_duration_seconds == 3300
    assert r.transit_legs == 2        # Bus + Metro
    assert r.transfers == 1           # transit_legs - 1
    assert r.walking_duration_seconds == 900  # 300 + 420 + 180


def test_transit_route_to_route_candidate():
    """TRANSIT MapsRouteResponse converts to RouteCandidate with walking & transfers."""
    resp = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.TRANSIT,
        total_duration_seconds=3300,
        static_duration_seconds=3300,
        distance_meters=22000,
        has_traffic_data=False,
        walking_duration_seconds=900,
        transit_legs=2,
        transfers=1,
    )
    candidate = adapt_maps_response(resp)

    assert candidate.route_id == "maps_transit_0"
    assert candidate.mode == "metro"
    assert candidate.travel_time_minutes == pytest.approx(55.0)
    assert candidate.walking_minutes == pytest.approx(15.0)
    assert candidate.transfers == 1
    assert candidate.congestion_score == pytest.approx(0.15)


# =============================================================================
# 5. WALK Route Parsing
# =============================================================================

def test_walk_route_parsing():
    """Correctly parses WALK route duration."""
    client = make_client()
    fixture = get_walk_route_fixture()

    with patch("requests.post", return_value=mock_post(fixture)):
        req = MapsRouteRequest("A", "B", mode=TravelMode.WALK)
        routes = client.compute_routes(req)

    assert len(routes) == 1
    assert routes[0].total_duration_seconds == 900


def test_walk_route_to_route_candidate():
    """WALK MapsRouteResponse converts with zero cost, full walking minutes."""
    resp = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.WALK,
        total_duration_seconds=900,
        static_duration_seconds=900,
        distance_meters=1200,
    )
    candidate = adapt_maps_response(resp)

    assert candidate.route_id == "maps_walk_0"
    assert candidate.mode == "walking"
    assert candidate.cost == 0.0
    assert candidate.travel_time_minutes == pytest.approx(15.0)
    assert candidate.walking_minutes == pytest.approx(15.0)
    assert candidate.transfers == 0


# =============================================================================
# 6. Alternative Routes
# =============================================================================

def test_alternative_drive_routes_both_parsed():
    """Two DRIVE alternatives are parsed into two MapsRouteResponse objects."""
    client = make_client()
    fixture = get_drive_alternative_routes_fixture()

    with patch("requests.post", return_value=mock_post(fixture)):
        req = MapsRouteRequest("A", "B", mode=TravelMode.DRIVE, compute_alternatives=True)
        routes = client.compute_routes(req)

    assert len(routes) == 2
    assert routes[0].route_index == 0
    assert routes[1].route_index == 1
    # Second route is slower but distances differ
    assert routes[1].distance_meters > routes[0].distance_meters


# =============================================================================
# 7. Missing Optional Fields
# =============================================================================

def test_missing_description_defaults_gracefully():
    """MapsRouteResponse with missing optional description field is handled."""
    resp = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.DRIVE,
        total_duration_seconds=1800,
        distance_meters=12000,
        description=None,  # Missing description
    )
    candidate = adapt_drive_route(resp, 0)
    assert isinstance(candidate, RouteCandidate)


def test_route_without_traffic_data_uses_neutral_congestion():
    """When has_traffic_data is False, congestion defaults to neutral 0.5."""
    resp = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.DRIVE,
        total_duration_seconds=1800,
        static_duration_seconds=1800,
        distance_meters=10000,
        has_traffic_data=False,
    )
    candidate = adapt_drive_route(resp, 0)
    assert candidate.congestion_score == pytest.approx(0.5)


# =============================================================================
# 8. API Error Handling
# =============================================================================

def test_http_401_raises_maps_api_error():
    """HTTP 401 from Maps API raises MapsAPIError."""
    client = make_client()
    with patch("requests.post", return_value=mock_post({}, status_code=401)):
        with pytest.raises(MapsAPIError) as exc_info:
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))
    assert exc_info.value.status_code == 401


def test_http_429_raises_quota_error():
    """HTTP 429 from Maps API raises MapsAPIError for quota exceeded."""
    client = make_client()
    with patch("requests.post", return_value=mock_post({}, status_code=429)):
        with pytest.raises(MapsAPIError) as exc_info:
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))
    assert exc_info.value.status_code == 429


def test_empty_routes_raises_no_routes_error():
    """Empty routes list in response raises NoRoutesFoundError."""
    client = make_client()
    with patch("requests.post", return_value=mock_post(get_empty_routes_fixture())):
        with pytest.raises(NoRoutesFoundError):
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))


def test_missing_routes_key_raises_no_routes_error():
    """Missing 'routes' key in response raises NoRoutesFoundError."""
    client = make_client()
    with patch("requests.post", return_value=mock_post(get_no_routes_key_fixture())):
        with pytest.raises(NoRoutesFoundError):
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))


# =============================================================================
# 9. Cache Behavior
# =============================================================================

def test_cache_miss_then_hit(monkeypatch):
    """Second identical request hits cache and does not call the API again."""
    _clear_cache()
    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        return mock_post(get_drive_route_fixture())

    with patch("requests.post", side_effect=fake_post):
        get_candidate_routes(
            "Electronic City", "Koramangala",
            modes=[TravelMode.DRIVE],
            api_key="FAKE_KEY_99"
        )
        get_candidate_routes(
            "Electronic City", "Koramangala",
            modes=[TravelMode.DRIVE],
            api_key="FAKE_KEY_99"
        )

    assert call_count["n"] == 1, "Second call should have been served from cache"


def test_cache_expires_after_ttl(monkeypatch):
    """Cache entry expires after TTL and re-fetches from API."""
    _clear_cache()
    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        return mock_post(get_drive_route_fixture())

    with patch("requests.post", side_effect=fake_post):
        get_candidate_routes("A", "B", modes=[TravelMode.DRIVE], cache_ttl=0, api_key="FAKE_KEY_99")
        time.sleep(0.01)  # TTL=0 expires immediately
        get_candidate_routes("A", "B", modes=[TravelMode.DRIVE], cache_ttl=0, api_key="FAKE_KEY_99")

    assert call_count["n"] == 2, "Expired cache should trigger second API call"


# =============================================================================
# 10. Full service pipeline
# =============================================================================

def test_get_candidate_routes_returns_route_candidates():
    """get_candidate_routes returns a list of RouteCandidate objects."""
    _clear_cache()
    with patch("requests.post", return_value=mock_post(get_drive_route_fixture())):
        candidates = get_candidate_routes(
            "Electronic City", "Koramangala",
            modes=[TravelMode.DRIVE],
            api_key="FAKE_KEY_99"
        )
    assert len(candidates) == 1
    assert isinstance(candidates[0], RouteCandidate)
    assert candidates[0].travel_time_minutes > 0


def test_no_routes_for_mode_does_not_crash_other_modes():
    """NoRoutesFoundError for one mode is swallowed; other modes still returned."""
    _clear_cache()

    def fake_post(*args, **kwargs):
        body = kwargs.get("json", {})
        if body.get("travelMode") == "DRIVE":
            return mock_post(get_drive_route_fixture())
        # TRANSIT returns no routes
        return mock_post(get_empty_routes_fixture())

    with patch("requests.post", side_effect=fake_post):
        candidates = get_candidate_routes(
            "A", "B",
            modes=[TravelMode.DRIVE, TravelMode.TRANSIT],
            api_key="FAKE_KEY_99"
        )

    assert len(candidates) == 1
    assert candidates[0].mode == "cab"


def test_malformed_maps_response_raises():
    """Non-JSON and non-dict payloads raise MapsAPIError."""
    client = make_client()
    bad = MagicMock()
    bad.status_code = 200
    bad.json.side_effect = ValueError("no json")
    with patch("requests.post", return_value=bad):
        with pytest.raises(MapsAPIError, match="non-JSON"):
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))

    not_dict = MagicMock()
    not_dict.status_code = 200
    not_dict.json.return_value = ["not", "a", "dict"]
    with patch("requests.post", return_value=not_dict):
        with pytest.raises(MapsAPIError, match="malformed JSON"):
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))


def test_api_error_includes_message_without_key():
    """HTTP error surfaces API message and never includes the API key."""
    client = make_client(key="SUPER_SECRET_KEY_VALUE")
    err_body = {"error": {"message": "API key not valid", "status": "INVALID_ARGUMENT"}}
    with patch("requests.post", return_value=mock_post(err_body, status_code=400)):
        with pytest.raises(MapsAPIError) as exc_info:
            client.compute_routes(MapsRouteRequest("A", "B", TravelMode.DRIVE))
    assert exc_info.value.status_code == 400
    assert "API key not valid" in str(exc_info.value)
    assert "SUPER_SECRET_KEY_VALUE" not in str(exc_info.value)


def test_adapt_maps_response_dispatcher_and_provenance():
    """adapt_maps_response creates RouteCandidates; provenance marks heuristics."""
    from src.mobility.route_adapter import field_provenance

    drive = MapsRouteResponse(
        route_index=0,
        mode=TravelMode.DRIVE,
        total_duration_seconds=2280,
        static_duration_seconds=1800,
        distance_meters=18500,
        has_traffic_data=True,
        description="via NH 44",
    )
    candidate = adapt_maps_response(drive)
    assert candidate.route_id == "maps_drive_0"
    assert candidate.travel_time_minutes == pytest.approx(38.0)
    assert candidate.cost > 0  # heuristic cab estimate

    prov = field_provenance(TravelMode.DRIVE)
    assert prov["travel_time_minutes"] == "live"
    assert prov["cost"] == "heuristic"
    assert prov["data_source"] == "google_maps_routes"

    transit_prov = field_provenance(TravelMode.TRANSIT)
    assert transit_prov["walking_minutes"] == "live"
    assert transit_prov["cost"] == "heuristic"
