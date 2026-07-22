# Development Plan

This plan keeps the HTTP query contract as the canonical way to compose
per-test behavior. Query parameters work well for concurrent test cases because
each URL is self-contained and counters are isolated by `run_id`.

## 0.2.0: composable catalog scenarios

Status: implemented in the source tree.

- Add `total_pages` so a test can request between 1 and 20 catalog pages.
- Add `failure_delay_ms` so transient `503` responses can be delayed without
  replacing the `transient` scenario with `slow`.
- Preserve both parameters through protected-catalog login redirects.
- Document copy-paste commands for Windows, Linux, and macOS.
- Cover ten-page pagination and delayed recovery in tests and OpenAPI.

Acceptance:

- `total_pages=10` returns 50 deterministic items over ten pages.
- `protected=true&total_pages=10` returns to the same ten-page catalog after login.
- `scenario=transient&fail_for=2&failure_delay_ms=1500` delays and rejects the
  first two attempts per page, then recovers.

## 0.3.0: named presets and config files

Status: planned.

Add optional startup configuration for teams that repeat the same scenario
sets. Query parameters remain available and override preset defaults.

Proposed CLI:

```text
automation-test-stand --config scenarios.toml
automation-test-stand --preset login-delayed-retry
automation-test-stand --list-presets
automation-test-stand --print-url login-delayed-retry
```

Proposed TOML shape:

```toml
[presets.login-delayed-retry]
protected = true
scenario = "transient"
total_pages = 10
fail_for = 2
failure_delay_ms = 1500
```

Acceptance:

- Invalid preset names or values fail at startup with actionable messages.
- `--print-url` produces a URL that recreates the preset without the config file.
- Query parameters override only the fields explicitly present in the request.
- Parallel runs using different `run_id` values remain isolated.
- The default server behavior remains backward compatible.

## Later candidates

- A small `/scenario-builder` page that generates URLs without changing server state.
- Configurable items per page and deterministic data seeds.
- Contract fixtures for consumers in languages other than Python.
- Deprecation metadata for renamed parameters before a `1.0.0` contract.
