# Public contract and compatibility policy

This document defines the contract intended for the 1.0 release line of
Resilient Automation Test Stand. The generated
[OpenAPI snapshot](api/openapi.json) remains the machine-readable HTTP contract.

## Compatibility commitment

The project follows semantic versioning from `1.0.0` onward.

- Patch releases may fix defects but do not change documented successful response
  shapes, query names, CLI option names, scenario semantics, or stable browser
  locators.
- Minor releases may add optional fields, scenarios, parameters, or CLI options
  without changing existing documented behavior.
- Breaking changes require the next major version. A planned removal will name a
  replacement and remain documented for at least one minor release when practical.
- The 1.0 line supports Python 3.11, 3.12, and 3.13. Dropping a supported Python
  version is a breaking change.
- This package is a runnable test stand, not a supported Python library API.
  Python implementation symbols not documented here are internal.

Fixed credentials, in-memory counters, and the administrative reset endpoint
are test-only features, not production authentication or persistence features.

## Stable HTTP contract

| Method and path | Stable behavior |
| --- | --- |
| `GET /health` | Returns `{"status": "ok"}` when the process is ready. |
| `GET /catalog` | Returns the JavaScript catalog shell; a protected request redirects with `303` to `/login`. |
| `GET /api/catalog` | Returns one deterministic `CatalogPage` JSON response or the documented scenario failure. |
| `GET /login` | Returns the fixed demo login form. |
| `POST /login` | Accepts form data, sets the demo session cookie on success, then redirects with `303` to a local catalog URL. |
| `POST /admin/reset` | Test-only: clears in-memory attempt counters and returns `clearedCounters`. |

`/api-docs` is the stable interactive presentation of the OpenAPI contract.

### Catalog query parameters

`GET /catalog` and `GET /api/catalog` accept the same scenario parameters,
except that `protected` exists only on `/catalog`; `page` exists only on
`/api/catalog`.

| Parameter | Default | Valid values | Meaning |
| --- | --- | --- | --- |
| `page` | `1` | integer `1..20` | API page to fetch. |
| `scenario` | `success` | `success`, `transient`, `permanent`, `slow`, `resume`, `dom-change`, `duplicates` | Deterministic behavior. |
| `run_id` | `manual` | any string | Opaque identifier that isolates counters by `(run_id, scenario, page)`. |
| `total_pages` | `4` | integer `1..20` | Number of catalog pages exposed. |
| `fail_for` | `2` | integer `0..10` | Initial `503` responses per page in `transient`. |
| `failure_delay_ms` | `0` | integer `0..30000` | Delay before each transient `503`. |
| `delay_ms` | `1500` | integer `0..30000` | Delay per API response in `slow`. |
| `fail_page` | `3` | integer `1..20` | Permanently failing page in `resume`. |
| `protected` | `false` | boolean | Require demo login for `/catalog`; it does not protect `/api/catalog`. |

An active TOML preset provides defaults. A query parameter overrides only its
matching preset field. With no active preset, the defaults above apply.

### Response and failure semantics

`GET /api/catalog` returns `page`, `total_pages`, `items`, `scenario`, and
`attempt`. Every item has stable `id`, `name`, and `price` fields. A page has
five items unless it is greater than `total_pages`, in which case `items` is
empty.

- `transient` returns `503` with `Retry-After: 1` for the first `fail_for`
  attempts for each `(run_id, scenario, page)`, then returns `200`.
- `permanent` returns `500` on every attempt.
- `resume` returns `500` only for `fail_page`; other pages continue to work.
- `slow` delays the response before returning the normal page.
- `duplicates` repeats the previous page's final ID as the next page's first ID.
- `dom-change` preserves `data-testid` locators while changing CSS classes and
  element nesting.
- Invalid constrained values return FastAPI's standard `422` validation body.

Scenario failures expose `detail.code` as one of
`TRANSIENT_CATALOG_FAILURE`, `PERMANENT_CATALOG_FAILURE`, or
`CHECKPOINT_RESUME_FAILURE`. Consumers may assert these codes but not free-form
error wording.

### Browser and demo-login contract

The browser catalog keeps these locators stable through 1.x:
`catalog`, `catalog-item`, `item-name`, `item-price`, `next-page`, and
`catalog-error` (each used as a `data-testid`). The `dom-change` scenario makes
CSS classes and nesting deliberately unstable; consumers should use these
locators, roles, and labels instead.

Protected scenarios accept only the public test credentials `demo` /
`automation`. A successful login sets `demo_session=authenticated` with
`HttpOnly` and `SameSite=Lax`, then redirects only to a local path. Invalid
credentials return `401`; they must never be reused outside this stand.

## Stable CLI contract

| Command or option | Stable behavior |
| --- | --- |
| `automation-test-stand` | Starts the server with built-in defaults. |
| `--host HOST` | Bind host; default `127.0.0.1`. |
| `--port PORT` | Bind port; default `8080`. |
| `--log-level LEVEL` | Uvicorn log level; default `info`. |
| `--config PATH` | TOML preset file; required by preset operations. |
| `--preset NAME` | Starts the server with named preset defaults. |
| `--list-presets` | Lists preset names in stable lexicographical order and exits. |
| `--print-url NAME` | Prints a complete, portable catalog URL and exits. |

`--preset`, `--list-presets`, and `--print-url` are mutually exclusive. Invalid
or unknown presets and missing config produce actionable argparse errors. Preset
files accept only documented `ScenarioDefaults` fields and reject unknown fields.

## Contract verification

Every public-contract change requires:

1. an updated behavior test;
2. a reviewed compatibility note and changelog entry;
3. an updated OpenAPI snapshot when HTTP/OpenAPI changes;
4. a semantic-versioning decision;
5. a C# compatibility review before a stable release.
