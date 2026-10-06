"""A small client for Open-Meteo (https://open-meteo.com): keyless, no account.

This is the plugin's ONLY network I/O. The hosts it contacts, both HTTPS on 443:

* ``geocoding-api.open-meteo.com``: place name -> coordinates
* ``api.open-meteo.com``: coordinates -> daily forecast

What leaves the machine: the place name the owner (or the model) typed, and the resolved
coordinates. Nothing else: no identity, no credentials, no headers beyond the library's.
Every request is logged with ``log_egress`` (``iris_harness.sdk.logging``).

The HTTP transport is a constructor argument, so a test serves canned responses through
``httpx.MockTransport`` and nothing touches a socket.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx
from iris_harness.sdk.capabilities import Forecast, ForecastPeriod
from iris_harness.sdk.logging import log_egress

from .codes import describe

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
EGRESS_HOSTS = ("geocoding-api.open-meteo.com", "api.open-meteo.com")

MAX_DAYS = 16  # what the service serves
TIMEOUT_S = 10.0

_DAILY = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_probability_max,wind_speed_10m_max"
)


class WeatherError(Exception):
    """The forecast could not be had: the message says why, in words fit for the owner."""


def clamp_days(days: int) -> int:
    return max(1, min(int(days), MAX_DAYS))


def geocode_params(location: str) -> dict[str, Any]:
    return {"name": location.strip(), "count": 1, "language": "en", "format": "json"}


def forecast_params(latitude: float, longitude: float, days: int) -> dict[str, Any]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "daily": _DAILY,
        "timezone": "auto",
        "forecast_days": clamp_days(days),
        "wind_speed_unit": "kmh",
    }


def parse_place(payload: dict[str, Any], location: str) -> tuple[float, float, str]:
    """(latitude, longitude, "Name, Region, Country") of the best match."""
    results = payload.get("results") or []
    if not results:
        raise WeatherError(f"no place found called {location!r}")
    top = results[0]
    try:
        lat, lon = float(top["latitude"]), float(top["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError("the geocoder returned a place without coordinates") from exc
    parts = [top.get("name"), top.get("admin1"), top.get("country")]
    label = ", ".join(dict.fromkeys(str(p) for p in parts if p))
    return lat, lon, label or location.strip()


def parse_forecast(payload: dict[str, Any], place: str, now: datetime | None = None) -> Forecast:
    """The service's daily block as a ``Forecast`` (one period per day)."""
    daily = payload.get("daily") or {}
    days = daily.get("time") or []
    if not days:
        raise WeatherError("the forecast service returned no days")
    tz = timezone(timedelta(seconds=int(payload.get("utc_offset_seconds") or 0)))

    def column(key: str) -> list[Any]:
        values = list(daily.get(key) or [])
        return values + [None] * (len(days) - len(values))

    codes, highs, lows = (
        column("weather_code"),
        column("temperature_2m_max"),
        column("temperature_2m_min"),
    )
    rain, wind = column("precipitation_probability_max"), column("wind_speed_10m_max")
    periods: list[ForecastPeriod] = []
    for i, day in enumerate(days):
        if highs[i] is None:
            continue  # a day without a temperature is not a forecast
        start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=tz)
        summary = describe(int(codes[i])) if codes[i] is not None else describe(-1)
        if lows[i] is not None:
            summary = f"{summary}, low {float(lows[i]):.0f} C"
        periods.append(
            ForecastPeriod(
                start=start,
                end=start + timedelta(days=1),
                temperature_c=float(highs[i]),
                precipitation_probability=None if rain[i] is None else float(rain[i]) / 100.0,
                wind_speed_kph=None if wind[i] is None else float(wind[i]),
                summary=summary,
            )
        )
    if not periods:
        raise WeatherError("the forecast service returned no usable days")
    return Forecast(location=place, issued_at=now or datetime.now(UTC), periods=tuple(periods))


def _log(url: str, status: int | str, purpose: str) -> None:
    log_egress(destination=url, method="GET", purpose=purpose, kind="service", status=status)


def _json(response: httpx.Response, purpose: str) -> dict[str, Any]:
    _log(str(response.request.url.copy_with(query=None)), response.status_code, purpose)
    if response.status_code != 200:
        raise WeatherError(f"the weather service answered HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise WeatherError("the weather service returned something that is not JSON") from exc
    if not isinstance(body, dict):
        raise WeatherError("the weather service returned an unexpected shape")
    return body


class OpenMeteo:
    """Blocking client (the ReAct tool is a plain function)."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def forecast(self, location: str, days: int = 3) -> Forecast:
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S) as http:
                geo = _json(http.get(GEOCODING_URL, params=geocode_params(location)), "geocode")
                lat, lon, place = parse_place(geo, location)
                body = _json(
                    http.get(FORECAST_URL, params=forecast_params(lat, lon, days)), "forecast"
                )
        except httpx.HTTPError as exc:
            raise WeatherError(
                f"the weather service could not be reached ({type(exc).__name__})"
            ) from exc
        return parse_forecast(body, place)


class AsyncOpenMeteo:
    """Async client (the ``weather.forecast`` capability's methods are coroutines)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def forecast(self, location: str, days: int = 3) -> Forecast:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S) as http:
                geo = _json(
                    await http.get(GEOCODING_URL, params=geocode_params(location)), "geocode"
                )
                lat, lon, place = parse_place(geo, location)
                body = _json(
                    await http.get(FORECAST_URL, params=forecast_params(lat, lon, days)),
                    "forecast",
                )
        except httpx.HTTPError as exc:
            raise WeatherError(
                f"the weather service could not be reached ({type(exc).__name__})"
            ) from exc
        return parse_forecast(body, place)
