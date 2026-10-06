"""Canned Open-Meteo responses, served through ``httpx.MockTransport``: no socket is opened."""

from __future__ import annotations

import httpx
import pytest

GEOCODE = {
    "results": [
        {
            "name": "Lisbon",
            "latitude": 38.71667,
            "longitude": -9.13333,
            "country": "Portugal",
            "admin1": "Lisboa",
        }
    ]
}
FORECAST = {
    "utc_offset_seconds": 3600,
    "daily": {
        "time": ["2026-10-06", "2026-10-07"],
        "weather_code": [0, 61],
        "temperature_2m_max": [24.4, 21.0],
        "temperature_2m_min": [15.2, 14.0],
        "precipitation_probability_max": [5, 70],
        "wind_speed_10m_max": [12.3, 25.0],
    },
}


class Recorder:
    """The requests the transport saw, so a test can assert what left the plugin."""

    def __init__(self, geocode: dict | None = None, forecast: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._geocode = GEOCODE if geocode is None else geocode
        self._forecast = FORECAST if forecast is None else forecast

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=self._geocode)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(200, json=self._forecast)
        return httpx.Response(404)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def transport(recorder: Recorder) -> httpx.MockTransport:
    return httpx.MockTransport(recorder)
