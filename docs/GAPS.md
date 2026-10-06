# SDK gaps found while building this plugin

Each entry says what was tried, what happened, and the core change proposed. None is
worked around in this repository. Built against an iris-harness wheel in a fresh Python 3.12
venv. Re-checked on 2026-10-06 against a wheel built from iris-harness `main` at `2166717`;
each entry below says whether that re-check changed it. Tracking issues are in
evarness-ai/iris-harness.

## GAP-1 (important): no governance of a tool's network egress, and no way to declare it

Still open at `2166717` (iris-harness#103). Re-run: `PluginManifest` still rejects `egress:`
as an extra key, and still accepts only `sends_to: search_engine`.

- Tried: declare the hosts the network tool contacts in `manifest.yaml`
  (`egress: {hosts: [api.open-meteo.com]}`), and mark the tool's destination with
  `sends_to`.
- Result: `PluginManifest` rejects the first (`egress: Extra inputs are not permitted`) and
  the second accepts only `search_engine` (`tools.t.sends_to: Input should be
  'search_engine'`, tried `weather_service`).
- What exists instead: `config/governance/egress.yaml` is the LLM-prompt class-to-tier
  policy (secret/personal/internal/public vs tier_1..3). Nothing mediates an in-process
  plugin's own HTTP. The only controls are the plugin reporting itself via
  `sdk.logging.log_egress` and `testing.no_network()` in tests. A `trusted-third-party`
  plugin can contact any host and the operator's only record is whatever the plugin chose
  to log.
- Consequence: the riskiest path in the milestone (issue #79's "exercises egress
  governance for a third-party plugin") is, today, honour-system. This plugin records its
  hosts in `docs/EGRESS.md` by hand.
- Also: a place name can be personal (a home address). With only `sends_to: search_engine`
  the owner-PII guards (ADR-0125) cannot be told that this tool's arguments leave to a
  weather service.
- Proposed core fix: a manifest field declaring allowed outbound hosts per plugin
  (e.g. `egress: {hosts: [...]}`), compiled into the kernel's policy next to
  `egress.yaml`; a governed HTTP client handed to plugins (a `HarnessServices.http` field
  or an `sdk.http` module) that enforces the allowlist and writes the ledger row itself;
  a drift check "contacted a host not declared"; and a generic `sends_to` destination
  (`external_service`) for the owner-PII guards.

## GAP-2: iris-harness is not installable from an index

Still open at `2166717` (iris-harness#108): PyPI answers 404 for `iris-harness`, and the
repository has no tags (one draft release).

- Tried: `pip install iris-harness` (the plugin's declared dependency, `>=0.1,<0.2`).
- Result: PyPI answers 404 for `iris-harness`. The plugin installs only after building a
  wheel from a clone (`python -m build --wheel`), which is what this repo's CI does.
- Proposed: publish tagged releases (or at least GitHub release wheels) so a third party
  can pin a version, and so G7 (works on two consecutive versions) is testable.

## GAP-3: scaffold ergonomics (minor)

Re-run at `2166717` (iris-harness#107): the command and README points below are unchanged; the
manifest template now carries `party: untrusted`, which the first run did not have.

- `iris plugins new weather-now` as written in the issue fails: `Missing option '--kind'`.
  The working command is `iris plugins new weather-now --kind tool --dir <dir>`.
- The generated README says `iris plugin new` (singular); the command group is `plugins`.
- The directory is `<dir>/<name>` (here `weather-now`); the repository name
  `iris-weather-plugin` needs a rename. The distribution is `iris-plugin-weather-now`.
- The `tool` scaffold is one sync read tool. It has no `capabilities:`
  block, no network/async example and no `pytest-asyncio` in the test extra, so a
  capability provider (async by Protocol) needs those added by hand. Proposed: a
  `capability-provider` kind.

## GAP-4 (design note, not blocking): no HTTP/transport injection point

Unchanged at `2166717` (iris-harness#107, #103).

- `setup(api)` receives nothing to configure it with, so the plugin exposes
  `make_setup(transport, async_transport)` and the entry point is `setup = make_setup()`.
  Tests mount their own through `iris_harness.testing.plugin`. This works and uses only
  the stable tier, but every network plugin will reinvent it. Resolved by the governed
  HTTP client proposed in GAP-1.

## Observation: `weather.forecast` schema

`ForecastPeriod` carries one `temperature_c`. Open-Meteo gives a daily high and low; this
plugin reports the high as `temperature_c` and puts the low in `summary` text. A
`temperature_min_c` field would avoid that. Not a blocker.

## GAP-5 (noise, core wheel; intermittent): the test process can abort at interpreter exit

Seen at `2166717` on macOS: `pytest` printed `23 passed`, then the process died with
`libc++abi: terminating due to uncaught exception of type std::__1::system_error:
recursive_mutex lock failed: Invalid argument` and a non-zero exit status, which fails
`scripts/ci_local.sh`. The same gate passed on other runs, so it is intermittent. The cause was not traced (it was not
checked whether it needs the harness imported). Re-run the gate if it happens.

## Not checked (needs a running stack)

`iris plugins show weather-now` needs a running IRIS API. Discovery was verified through
the `iris_harness.plugins` entry point and by mounting through the test harness; the built
wheel contains `manifest.yaml`.
