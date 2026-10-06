# What this plugin needs from the host: network egress

Open-Meteo is keyless: there is no secret to configure and no account. The plugin's only
network I/O is `src/iris_plugin_weather_now/openmeteo.py`.

| Host | Port | Purpose | Sent |
|---|---|---|---|
| `geocoding-api.open-meteo.com` | 443 (HTTPS) | place name -> coordinates | the place name as given |
| `api.open-meteo.com` | 443 (HTTPS) | coordinates -> daily forecast | latitude, longitude, day count |

An operator who restricts outbound traffic (firewall, proxy, a locked-down VM) must allow
exactly those two hosts. Nothing else is contacted. Timeout is 10 s per request; a failure
is returned to the model as an `error:` observation (tool) or `CapabilityUnavailable`
(capability), never raised out of the plugin.

## What the harness gives the plugin for this today

Verified against iris-harness `main` at `2166717` (the test suite and the manifest checks below were run against a wheel built from it):

- Each request is recorded with `iris_harness.sdk.logging.log_egress` (`EGRESS service GET
  -> <url without query> purpose=geocode|forecast status=<code>`). This is the plugin
  reporting on itself.
- The manifest declares `weather_forecast` as `effect: read`, `content: external`, so the
  kernel records PRE/POST_TOOL_USE rows and the result is eligible for IRIS's
  retrieved-content injection guard. That guard is opt-in (`IRIS_GOVERNANCE_PROMPT_GUARD`)
  and needs its classifier; by default nothing scans the result (iris-harness#104).
- `config/governance/egress.yaml` is the LLM-prompt class-to-tier policy. It does not
  govern a tool's own network calls.
- The manifest cannot state the hosts above, and nothing in the harness enforces them. See
  GAPS.md, GAP-1 (iris-harness#103).
