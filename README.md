# Resilient Automation Test Stand

A deterministic FastAPI target for browser automation, retry, pagination,
authentication, DOM changes, cancellation, and recovery scenarios.

The stand is deliberately stateful within one process: retry counters are
isolated by `run_id` and can be reset between test cases. It is test
infrastructure and is not intended to serve production traffic.

## Quick start with Python

Requirements: Python 3.11 or newer.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
automation-test-stand --port 8080
```

Linux and macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
automation-test-stand --port 8080
```

The module entry point is equivalent on every platform:

```bash
python -m resilient_automation_test_stand --port 8080
```

## Quick start with Docker Compose

These commands are the same in PowerShell, Linux shells, and macOS Terminal:

```bash
docker compose up --build --detach --wait
docker compose down
```

Check readiness while the service is running.

Windows PowerShell:

```powershell
Invoke-RestMethod http://localhost:8080/health
```

Linux and macOS:

```bash
curl --fail http://localhost:8080/health
```

The development image is named `resilient-automation-test-stand:dev`.
Released images are published as
`ghcr.io/bockuden/resilient-automation-test-stand:<version>`.

## Scenario cookbook

Start the server first, then use one of the commands below. Protected scenarios
redirect to the login form; use username `demo` and password `automation`.

### Windows PowerShell

```powershell
$catalog = 'http://localhost:8080/catalog'

# Ten successful catalog pages.
Start-Process "$catalog?scenario=success&run_id=ten-pages&total_pages=10"

# Login, then ten successful catalog pages.
Start-Process "$catalog?protected=true&scenario=success&run_id=login-ten-pages&total_pages=10"

# Login, then two delayed 503 responses per page before recovery.
Start-Process "$catalog?protected=true&scenario=transient&run_id=login-delayed-503&total_pages=10&fail_for=2&failure_delay_ms=1500"
```

### Linux

```bash
catalog='http://localhost:8080/catalog'

xdg-open "${catalog}?scenario=success&run_id=ten-pages&total_pages=10"
xdg-open "${catalog}?protected=true&scenario=success&run_id=login-ten-pages&total_pages=10"
xdg-open "${catalog}?protected=true&scenario=transient&run_id=login-delayed-503&total_pages=10&fail_for=2&failure_delay_ms=1500"
```

### macOS

```bash
catalog='http://localhost:8080/catalog'

open "${catalog}?scenario=success&run_id=ten-pages&total_pages=10"
open "${catalog}?protected=true&scenario=success&run_id=login-ten-pages&total_pages=10"
open "${catalog}?protected=true&scenario=transient&run_id=login-delayed-503&total_pages=10&fail_for=2&failure_delay_ms=1500"
```

The delayed transient example waits 1.5 seconds before each of the first two
`503` responses on every page. A manual browser displays the error and can be
reloaded; an automation worker can exercise its retry policy and recover on the
third attempt.

## Named scenario presets

For repeated scenarios, the same values can be stored in a TOML file instead
of copied into every startup command. The repository includes
[`examples/scenarios.toml`](examples/scenarios.toml) with the three cookbook
scenarios above.

These CLI commands are identical in PowerShell, Linux, and macOS shells:

```bash
automation-test-stand --config examples/scenarios.toml --list-presets
automation-test-stand --config examples/scenarios.toml --print-url login-delayed-retry
automation-test-stand --config examples/scenarios.toml --preset login-delayed-retry --port 8080
```

`--print-url` emits a self-contained URL that no longer depends on the config
file. `--preset` starts the server with that preset as its defaults. An explicit
query parameter overrides only the matching preset field, so the following URL
uses the preset's ten pages but disables its transient failures:

```text
http://localhost:8080/catalog?scenario=success&run_id=override-example
```

Preset files use this shape; omitted fields inherit the built-in defaults:

```toml
[presets.login-delayed-retry]
protected = true
scenario = "transient"
total_pages = 10
fail_for = 2
failure_delay_ms = 1500
```

To fetch all ten pages directly from the API, use either loop below.

Windows PowerShell:

```powershell
1..10 | ForEach-Object {
    Invoke-RestMethod "http://localhost:8080/api/catalog?scenario=success&run_id=api-ten-pages&page=$_&total_pages=10"
}
```

Linux and macOS:

```bash
page=1
while [ "$page" -le 10 ]; do
  curl --fail "http://localhost:8080/api/catalog?scenario=success&run_id=api-ten-pages&page=${page}&total_pages=10"
  printf '\n'
  page=$((page + 1))
done
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Container and service readiness |
| `GET` | `/catalog` | JavaScript-rendered catalog and pagination shell |
| `GET` | `/api/catalog` | Deterministic paginated catalog data |
| `GET` | `/login` | Predictable login form |
| `POST` | `/login` | Authenticate the demo user and set a session cookie |
| `POST` | `/admin/reset` | Clear all in-memory attempt counters |
| `GET` | `/api-docs` | Interactive OpenAPI documentation |

## Scenario parameters

Both `/catalog` and `/api/catalog` accept the parameters below. `/api/catalog`
also accepts `page` from 1 through 20.

| Parameter | Built-in default | Meaning |
| --- | --- | --- |
| `scenario` | `success` | Selects the deterministic behavior described below |
| `run_id` | `manual` | Isolates request-attempt counters between test cases |
| `total_pages` | `4` | Number of catalog pages to expose (1-20) |
| `fail_for` | `2` | Initial `503` responses per page in `transient` (0-10) |
| `failure_delay_ms` | `0` | Delay before each transient `503` response (0-30000 ms) |
| `delay_ms` | `1500` | Delay per API request in `slow` (0-30000 ms) |
| `fail_page` | `3` | Permanently failing page in `resume` (1-20) |
| `protected` | `false` | Require the demo login before serving `/catalog` |

## Scenarios

| Scenario | Behavior |
| --- | --- |
| `success` | Returns `total_pages` pages of five unique items each |
| `transient` | Returns `503` with `Retry-After: 1` for the first `fail_for` attempts of each page, then recovers |
| `permanent` | Always returns `500` from the catalog API |
| `slow` | Delays every catalog API response by `delay_ms`, enabling timeout and cancellation tests |
| `resume` | Loads other pages but returns `500` on `fail_page`, enabling durable checkpoint and resume tests |
| `dom-change` | Changes catalog element names and CSS classes while preserving stable `data-testid` locators |
| `duplicates` | Repeats the previous page's final item as the next page's first item |

The same `run_id`, scenario, and page share an attempt counter. Call
`POST /admin/reset` or choose a fresh `run_id` when a test needs clean state.

## Development and contract checks

After activating the virtual environment:

```bash
python -m pip install -e '.[dev]' build
python -m pytest
python scripts/export_openapi.py --check
python -m build
```

The committed contract is [docs/api/openapi.json](docs/api/openapi.json). If an
endpoint or model changes, regenerate it with:

```bash
python scripts/export_openapi.py
```

Contract changes require an updated snapshot, [release notes](CHANGELOG.md), a
package version change, and a backward-compatibility review. The release
roadmap is tracked in [the development plan](docs/development-plan.md).

## License

MIT. See [LICENSE](LICENSE).
