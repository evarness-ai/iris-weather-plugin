"""Weather Now: two tools on IRIS's governed ReAct loop, and ``weather.forecast``.

* ``weather_code_meaning``: deterministic read. A WMO code in, its conditions out.
* ``weather_forecast``: network-backed read against keyless Open-Meteo.
* ``weather.forecast`` capability (``iris_harness.sdk.capabilities.WeatherForecast``):
  the same forecast for other plugins, through ``api.provide``.

``manifest.yaml`` declares both tools and the capability; one the manifest does not list
is refused when the plugin mounts. Governance (the kernel's PRE/POST_TOOL_USE rows, the
audit trail, the injection scan of ``content: external``) is the harness's: nothing here
calls a hook.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from iris_harness.sdk import PluginAPI
from iris_harness.sdk.capabilities import CapabilityUnavailable, Forecast

from . import codes
from .openmeteo import MAX_DAYS, AsyncOpenMeteo, OpenMeteo, WeatherError

CODE_TOOL = "weather_code_meaning"
CODE_DESCRIPTION = (
    "Explain a WMO weather code (the numbers weather services use) in words. "
    'Args: {"code": int}.'
)
FORECAST_TOOL = "weather_forecast"
FORECAST_DESCRIPTION = (
    "Get the daily weather forecast for a place from Open-Meteo. "
    f'Args: {{"location": str, "days": int (1-{MAX_DAYS}, default 3)}}.'
)


def code_meaning(args: dict[str, Any]) -> str:
    """The deterministic tool: plain Python, no I/O."""
    raw = args.get("code")
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return 'error: pass the WMO code as {"code": 61}'
    try:
        code = int(raw)
    except ValueError:
        return 'error: pass the WMO code as {"code": 61}'
    return json.dumps(
        {"code": code, "conditions": codes.describe(code), "category": codes.category(code)}
    )


def render(forecast: Forecast) -> str:
    """The forecast as the observation the model reads."""
    lines = [f"Forecast for {forecast.location}:"]
    for p in forecast.periods:
        rain = (
            "rain chance n/a"
            if p.precipitation_probability is None
            else f"rain chance {p.precipitation_probability:.0%}"
        )
        wind = "" if p.wind_speed_kph is None else f", wind up to {p.wind_speed_kph:.0f} km/h"
        lines.append(
            f"- {p.start.date().isoformat()}: {p.summary}, high {p.temperature_c:.0f} C, "
            f"{rain}{wind}"
        )
    return "\n".join(lines)


def make_forecast_tool(client: OpenMeteo) -> Callable[[dict[str, Any]], str]:
    def run(args: dict[str, Any]) -> str:
        location = args.get("location")
        if not isinstance(location, str) or not location.strip():
            return 'error: pass the place as {"location": "Lisbon"}'
        days = args.get("days", 3)
        if isinstance(days, bool) or not isinstance(days, int | float | str):
            return "error: days must be a whole number"
        try:
            return render(client.forecast(location, int(days)))
        except ValueError:
            return "error: days must be a whole number"
        except WeatherError as exc:
            return f"error: {exc}"

    return run


class _Provider:
    """The ``weather.forecast`` implementation (the Protocol's one coroutine)."""

    def __init__(self, client: AsyncOpenMeteo) -> None:
        self._client = client

    async def forecast(self, location: str, days: int = 3) -> Forecast:
        try:
            return await self._client.forecast(location, days)
        except WeatherError as exc:
            raise CapabilityUnavailable(str(exc)) from exc


def make_setup(
    transport: httpx.BaseTransport | None = None,
    async_transport: httpx.AsyncBaseTransport | None = None,
) -> Callable[[PluginAPI], None]:
    """``setup`` with its HTTP transports as parameters.

    The entry point is ``setup`` below (real network). A test builds its own with
    ``httpx.MockTransport`` and mounts it through ``iris_harness.testing.plugin``.
    """

    def configured(api: PluginAPI) -> None:
        api.register_tool(CODE_TOOL, CODE_DESCRIPTION, code_meaning)
        api.register_tool(
            FORECAST_TOOL, FORECAST_DESCRIPTION, make_forecast_tool(OpenMeteo(transport))
        )
        api.provide("weather.forecast", _Provider(AsyncOpenMeteo(async_transport)))

    return configured


setup = make_setup()
