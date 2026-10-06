"""Weather Now's tests: each tool alone, then mounted in a real, governed IRIS.

``harness`` builds the runtime ``iris`` runs, in a throwaway home, on the scripted model
in ``model_script.yaml``, with the network refused. The forecast tool's HTTP goes to a
``httpx.MockTransport`` handed to ``make_setup``: the plugin's own seam, not a patch.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from iris_harness.sdk.capabilities import CapabilityUnavailable
from iris_harness.testing import assert_conformant, harness, no_network, plugin

from iris_plugin_weather_now import codes, openmeteo
from iris_plugin_weather_now import plugin as this_plugin
from iris_plugin_weather_now.openmeteo import AsyncOpenMeteo, OpenMeteo

NAME = "weather-now"
MANIFEST = Path(this_plugin.__file__).with_name("manifest.yaml")
SCRIPT = Path(__file__).with_name("model_script.yaml")


def mounted(transport: httpx.MockTransport):
    return plugin(this_plugin.make_setup(transport, transport), manifest=MANIFEST)


# -- the deterministic tool ------------------------------------------------------------


def test_code_meaning_is_a_pure_lookup() -> None:
    first = this_plugin.code_meaning({"code": 61})
    assert first == this_plugin.code_meaning({"code": 61})
    assert json.loads(first) == {"code": 61, "conditions": "Slight rain", "category": "rain"}
    assert json.loads(this_plugin.code_meaning({"code": "95"}))["category"] == "storm"
    assert json.loads(this_plugin.code_meaning({"code": 4242}))["category"] == "unknown"


@pytest.mark.parametrize("bad", [{}, {"code": "rain"}, {"code": None}, {"code": True}])
def test_code_meaning_bad_args_are_an_observation(bad: dict) -> None:
    assert this_plugin.code_meaning(bad).startswith("error:")


# -- the network-backed tool, against canned responses -----------------------------------


def test_forecast_tool_renders_the_forecast(transport, recorder) -> None:
    run = this_plugin.make_forecast_tool(OpenMeteo(transport))
    text = run({"location": "Lisbon", "days": 2})
    assert "Forecast for Lisbon, Lisboa, Portugal" in text
    assert "2026-10-06: Clear sky, low 15 C, high 24 C, rain chance 5%" in text
    assert "2026-10-07: Slight rain, low 14 C, high 21 C, rain chance 70%, wind up to 25" in text


def test_only_open_meteo_hosts_are_contacted_and_only_the_place_leaves(recorder, transport) -> None:
    this_plugin.make_forecast_tool(OpenMeteo(transport))({"location": "Lisbon", "days": 99})
    assert {r.url.host for r in recorder.requests} == set(openmeteo.EGRESS_HOSTS)
    assert all(r.url.scheme == "https" for r in recorder.requests)
    geocode, forecast = recorder.requests
    assert dict(geocode.url.params) == {
        "name": "Lisbon",
        "count": "1",
        "language": "en",
        "format": "json",
    }
    assert forecast.url.params["forecast_days"] == str(openmeteo.MAX_DAYS)  # clamped
    assert set(forecast.url.params) == {
        "latitude",
        "longitude",
        "daily",
        "timezone",
        "forecast_days",
        "wind_speed_unit",
    }
    assert set(geocode.headers) <= {"host", "accept", "accept-encoding", "connection", "user-agent"}


def test_unknown_place_is_an_error_observation() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    run = this_plugin.make_forecast_tool(OpenMeteo(transport))
    assert run({"location": "Nowhereville"}) == "error: no place found called 'Nowhereville'"


def test_service_errors_are_an_observation_not_an_exception() -> None:
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    assert "HTTP 503" in this_plugin.make_forecast_tool(OpenMeteo(down))({"location": "Lisbon"})

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    text = this_plugin.make_forecast_tool(OpenMeteo(httpx.MockTransport(unreachable)))(
        {"location": "Lisbon"}
    )
    assert text.startswith("error:") and "could not be reached" in text


@pytest.mark.parametrize(
    "bad", [{}, {"location": ""}, {"location": 5}, {"location": "x", "days": "many"}]
)
def test_forecast_bad_args(bad: dict, transport) -> None:
    assert this_plugin.make_forecast_tool(OpenMeteo(transport))(bad).startswith("error:")


def test_real_client_with_the_network_refused_fails_cleanly() -> None:
    """The shipped ``setup`` uses the real transport; under ``no_network`` it must degrade,
    not hang or raise out of the tool."""
    with no_network() as attempts:
        text = this_plugin.make_forecast_tool(OpenMeteo())({"location": "Lisbon"})
    assert text.startswith("error:")
    assert attempts, "the plugin should have tried to reach Open-Meteo (and been refused)"


def test_every_wmo_code_in_a_day_has_words() -> None:
    assert codes.describe(0) == "Clear sky"
    assert codes.describe(-1) == codes.UNKNOWN
    assert all(codes.describe(c) != codes.UNKNOWN for c in codes.WMO_CODES)


# -- the capability ------------------------------------------------------------------------


async def test_capability_provider_returns_a_forecast(transport) -> None:
    forecast = await AsyncOpenMeteo(transport).forecast("Lisbon", 2)
    assert forecast.location == "Lisbon, Lisboa, Portugal"
    assert [p.temperature_c for p in forecast.periods] == [24.4, 21.0]
    assert forecast.periods[1].precipitation_probability == pytest.approx(0.7)
    assert forecast.periods[0].end - forecast.periods[0].start == __import__("datetime").timedelta(
        days=1
    )


async def test_capability_cannot_answer_raises_unavailable() -> None:
    empty = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    provider = this_plugin._Provider(AsyncOpenMeteo(empty))
    with pytest.raises(CapabilityUnavailable):
        await provider.forecast("Nowhereville")


def test_manifest_declares_party_trust_and_capability() -> None:
    raw = yaml.safe_load(MANIFEST.read_text())
    assert raw["party"] == "trusted-third-party"
    assert raw["trust"] == "in-process"
    assert raw["capabilities"]["provides"] == ["weather.forecast"]
    assert set(raw["tools"]) == {"weather_code_meaning", "weather_forecast"}
    assert raw["tools"]["weather_code_meaning"]["effect"] == "read"
    assert raw["tools"]["weather_forecast"]["content"] == "external"


# -- mounted in a governed IRIS ---------------------------------------------------------------


def test_the_plugin_mounts_with_its_manifest(transport) -> None:
    with harness(plugins=[mounted(transport)]) as h:
        assert h.plugin_loaded(NAME), h.plugins()[NAME]


@pytest.mark.parametrize("entry", ["chat", "chat_stream"])
def test_the_model_calls_the_forecast_tool_through_the_governed_loop(entry, transport) -> None:
    with harness(plugins=[mounted(transport)], fake_model=SCRIPT) as h:
        ask = h.chat if entry == "chat" else h.chat_stream
        result = ask("What is the weather forecast for Lisbon?")
        assert result.answered, result.error
        assert result.text == "Lisbon looks clear and mild."
        assert [c.rule for c in h.model_calls()] == [
            "call the forecast tool",
            "answer from the forecast",
        ]
        assert h.audit_rows(hook_point="pre_tool_use")
        assert h.audit_rows(hook_point="post_tool_use")
        assert h.audit_gaps() == []


def test_governance_conformance(transport) -> None:
    """The harness's reusable suite: audit rows, caller stamping, coverage of every tool
    and of the capability's method, run as a consumer would call them."""
    assert_conformant(
        mounted(transport),
        tools={
            "weather_code_meaning": {"code": 3},
            "weather_forecast": {"location": "Lisbon", "days": 2},
        },
        capabilities={"weather.forecast": {"forecast": {"location": "Lisbon", "days": 2}}},
    )
