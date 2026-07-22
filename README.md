# Resilient Automation Test Stand

A deterministic FastAPI target for browser automation, retry, pagination,
authentication, DOM changes, cancellation, and recovery scenarios.

The stand is deliberately stateful within one process: retry counters are
isolated by `run_id` and can be reset between test cases. It is test
infrastructure and is not intended to serve production traffic.

## Run with Python

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
automation-test-stand --port 8080
```

The module entry point is equivalent:

```powershell
python -m resilient_automation_test_stand --port 8080
```

## Run with Docker Compose

```powershell
docker compose up --build --detach --wait
Invoke-RestMethod http://localhost:8080/health
docker compose down
```

The development Compose image is named
`resilient-automation-test-stand:dev`. Released images are published as
`ghcr.io/bockuden/resilient-automation-test-stand:<version>`.

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

Use username `demo` and password `automation` for protected catalog pages.
Add `protected=true` to `/catalog` to require authentication.

## Scenario parameters

Both `/catalog` and `/api/catalog` accept the parameters below. `/api/catalog`
also accepts `page` from 1 through 20.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `scenario` | `success` | Selects the deterministic behavior described below |
| `run_id` | `manual` | Isolates request-attempt counters between test cases |
| `fail_for` | `2` | Number of initial failures per page in `transient` (0–10) |
| `delay_ms` | `1500` | Delay per API request in `slow` (0–30000 ms) |
| `fail_page` | `3` | Permanently failing page in `resume` (1–20) |

## Scenarios

| Scenario | Behavior |
| --- | --- |
| `success` | Returns four pages of five unique items each |
| `transient` | Returns `503` with `Retry-After: 1` for the first `fail_for` attempts of each page, then recovers |
| `permanent` | Always returns `500` from the catalog API |
| `slow` | Delays every catalog API response by `delay_ms`, enabling timeout and cancellation tests |
| `resume` | Loads other pages but returns `500` on `fail_page`, enabling durable checkpoint and resume tests |
| `dom-change` | Changes catalog element names and CSS classes while preserving stable `data-testid` locators |
| `duplicates` | Repeats the previous page's final item as the next page's first item |

The same `run_id`, scenario, and page share an attempt counter. Call
`POST /admin/reset` or choose a fresh `run_id` when a test needs clean state.

## Development and contract checks

```powershell
python -m pip install -e '.[dev]' build
python -m pytest
python scripts/export_openapi.py --check
python -m build
```

The committed contract is [docs/api/openapi.json](docs/api/openapi.json). If an
endpoint or model changes, regenerate it with:

```powershell
python scripts/export_openapi.py
```

Contract changes also require release notes, a package version change, and a
backward-compatibility review.

## License

MIT. See [LICENSE](LICENSE).
