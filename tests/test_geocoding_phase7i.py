"""Phase 7I — Google Geocoding + Places autocomplete (mocked HTTP)."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.agent.orchestrator import resolve_coordinates
from src.mobility.geocoding import (
    geocode_bengaluru,
    place_details,
    places_autocomplete,
)


class _FakeResp:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}" if payload is not None else b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_geocode_bengaluru_parses_ok_result():
    session = MagicMock()
    session.get.return_value = _FakeResp(
        {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Indiranagar, Bengaluru, Karnataka, India",
                    "geometry": {"location": {"lat": 12.9784, "lng": 77.6408}},
                }
            ],
        }
    )
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key-not-real"}):
        result = geocode_bengaluru("Indiranagar", session=session)
    assert result is not None
    assert result.latitude == pytest.approx(12.9784)
    assert result.longitude == pytest.approx(77.6408)
    assert result.provider == "google_geocoding"
    # Key must not appear in call kwargs as a logged side channel — present in params only.
    params = session.get.call_args.kwargs.get("params") or session.get.call_args[1].get(
        "params"
    )
    assert params["key"] == "test-key-not-real"
    assert "region" in params


def test_geocode_returns_none_without_api_key():
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
        assert geocode_bengaluru("Koramangala") is None


def test_resolve_coordinates_falls_back_to_google():
    geo = MagicMock()
    geo.latitude = 12.91
    geo.longitude = 77.64

    with patch(
        "src.mobility.geocoding.geocode_bengaluru", return_value=geo
    ) as mocked:
        lat, lon, how = resolve_coordinates("Some Unknown Place XYZ", None, None)
    assert how == "google_geocoding"
    assert lat == pytest.approx(12.91)
    mocked.assert_called_once()


def test_resolve_coordinates_landmark_before_google():
    with patch("src.mobility.geocoding.geocode_bengaluru") as mocked:
        lat, lon, how = resolve_coordinates("Electronic City", None, None)
    assert how == "landmark_table"
    mocked.assert_not_called()
    assert lat is not None


def test_resolve_coordinates_can_disable_google():
    lat, lon, how = resolve_coordinates(
        "Totally Unknown Place 999", None, None, allow_google=False
    )
    assert how == "unresolved"
    assert lat is None


def test_places_autocomplete_and_details_new_api():
    session = MagicMock()

    def _post(url, headers=None, json=None, timeout=None):
        assert "places:autocomplete" in url
        assert headers["X-Goog-Api-Key"] == "test-key-not-real"
        assert "X-Goog-FieldMask" in headers
        assert json["input"] == "Kora"
        assert json["includedRegionCodes"] == ["in"]
        return _FakeResp(
            {
                "suggestions": [
                    {
                        "placePrediction": {
                            "placeId": "pid_1",
                            "text": {"text": "Koramangala, Bengaluru"},
                            "structuredFormat": {
                                "mainText": {"text": "Koramangala"},
                                "secondaryText": {"text": "Bengaluru"},
                            },
                        }
                    }
                ]
            }
        )

    def _get(url, headers=None, timeout=None):
        assert "/places/pid_1" in url or url.endswith("/places/pid_1")
        assert headers["X-Goog-Api-Key"] == "test-key-not-real"
        return _FakeResp(
            {
                "id": "pid_1",
                "displayName": {"text": "Koramangala"},
                "formattedAddress": "Koramangala, Bengaluru",
                "location": {"latitude": 12.9352, "longitude": 77.6245},
            }
        )

    session.post.side_effect = _post
    session.get.side_effect = _get
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key-not-real"}):
        suggestions, err = places_autocomplete("Kora", session=session)
        details, derr = place_details("pid_1", session=session)
    assert err is None and derr is None
    assert suggestions[0].place_id == "pid_1"
    assert suggestions[0].main_text == "Koramangala"
    assert details is not None
    assert details.latitude == pytest.approx(12.9352)


def test_places_autocomplete_permission_denied():
    session = MagicMock()
    session.post.return_value = _FakeResp(
        {"error": {"status": "PERMISSION_DENIED", "message": "API not enabled"}},
        status_code=403,
    )
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key-not-real"}):
        suggestions, err = places_autocomplete("Kora", session=session)
    assert suggestions == []
    assert err == "places_permission_denied"
