# iris-weather-plugin

An [IRIS](https://github.com/evarness-ai/iris-harness) plugin built entirely outside the
harness repository (issue evarness-ai/iris-harness#79), against an installed iris-harness
wheel. It adds:

| | |
|---|---|
| `weather_code_meaning` | deterministic read tool: a WMO weather code in, its conditions out. No I/O. |
| `weather_forecast` | network-backed read tool: daily forecast for a place from keyless [Open-Meteo](https://open-meteo.com). |
| `weather.forecast` capability | the same forecast for other plugins (`api.capability("weather.forecast")`). |

Manifest: `party: trusted-third-party`, `trust: in-process`. It imports only
`iris_harness.sdk` and `iris_harness.testing` (CI runs `check_stable_imports()`).

## Develop

iris-harness is not on PyPI yet (docs/GAPS.md GAP-2), so build a wheel from a clone and
install that, never the source tree:

```bash
git clone https://github.com/evarness-ai/iris-harness && python3.12 -m venv .venv
.venv/bin/pip install build && .venv/bin/python -m build --wheel iris-harness -o wheelhouse
.venv/bin/pip install wheelhouse/iris_harness-*.whl
.venv/bin/pip install -e ".[test]" && .venv/bin/python -m pytest
```

Tests need no network and no model server: HTTP goes to `httpx.MockTransport`, the model is
scripted (`tests/model_script.yaml`), and the harness refuses sockets.

## Run

Install the package beside IRIS and list it in a profile (`~/.iris/profile.yaml`):

```yaml
plugins:
  - name: weather-now
```

## Egress

The plugin contacts exactly `geocoding-api.open-meteo.com` and `api.open-meteo.com` over
HTTPS. See [docs/EGRESS.md](docs/EGRESS.md). Gaps found in the SDK: [docs/GAPS.md](docs/GAPS.md).

Apache-2.0. Commits are signed off (`git commit -s`).
