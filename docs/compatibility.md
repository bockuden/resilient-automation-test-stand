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
| `GET /api/catalog` | Returns one deterministic `CatalogPage` JSON response or a documented authentication/scenario failure. |
| `GET /login` | Returns the fixed demo login form. |
| `POST /login` | Accepts form data, sets the demo session cookie on success, then redirects with `303` to a local catalog URL. |
| `POST /admin/reset` | Test-only: clears attempt counters and session-expiry state, then returns `clearedCounters`. |

`/api-docs` is the stable interactive presentation of the OpenAPI contract.

### Catalog query parameters

`GET /catalog` and `GET /api/catalog` accept the same scenario and session
parameters. `resume_page` exists only on `/catalog`; `page` exists only on
`/api/catalog`.

| Parameter | Default | Valid values | Meaning |
| --- | --- | --- | --- |
| `page` | `1` | integer `1..20` | API page to fetch. |
| `scenario` | `success` | `success`, `transient`, `rate-limit`, `permanent`, `slow`, `resume`, `dom-change`, `duplicates`, `selector-failure`, `malformed-api` | Deterministic behavior. |
| `run_id` | `manual` | any string | Opaque identifier that isolates counters by `(run_id, scenario, page)`. |
| `total_pages` | `4` | integer `1..20` | Number of catalog pages exposed. |
| `fail_for` | `2` | integer `0..10` | Initial `503` responses per page in `transient`. |
| `failure_delay_ms` | `0` | integer `0..30000` | Delay before each transient `503`. |
| `rate_limit_for` | `2` | integer `0..10` | Initial `429` responses per page in `rate-limit`. |
| `retry_after_seconds` | `1` | integer `0..300` | `Retry-After` delta-seconds value in `rate-limit`. |
| `malformed_mode` | `invalid_json` | `invalid_json`, `truncated_json`, `wrong_content_type`, `missing_fields`, `wrong_field_type` | Deterministic contract violation emitted by `malformed-api`. |
| `expire_session_after_page` | unset | integer `1..20` | Expire an authenticated session before the following page. |
| `delay_ms` | `1500` | integer `0..30000` | Delay per API response in `slow`. |
| `fail_page` | `3` | integer `1..20` | Permanently failing page in `resume`. |
| `protected` | `false` | boolean | Require demo login for `/catalog` and its authenticated cookie for `/api/catalog`. |
| `resume_page` | `1` | integer `1..20` | Browser page loaded after login or re-login; `/catalog` only. |
| `selector_failure_target` | unset | `login_button`, `item`, `next_page` | Browser locator affected by `selector-failure`. |
| `selector_failure_mode` | unset | `missing`, `changed`, `multiple`, `delayed`, `hidden`, `disabled` | Deterministic locator failure behavior; must be paired with a target. |
| `selector_failure_page` | `1` | integer `1..20` | Page where the locator failure applies. |
| `selector_failure_delay_ms` | `500` | integer `1..5000` | Bounded visibility delay for the `delayed` mode. |

An active TOML preset provides defaults. A query parameter overrides only its
matching preset field. With no active preset, the defaults above apply.

### Response and failure semantics

`GET /api/catalog` returns `page`, `total_pages`, `items`, `scenario`, and
`attempt`. Every item has stable `id`, `name`, and `price` fields. A page has
five items unless it is greater than `total_pages`, in which case `items` is
empty.

- `transient` returns `503` with `Retry-After: 1` for the first `fail_for`
  attempts for each `(run_id, scenario, page)`, then returns `200`.
- `rate-limit` returns `429` with the configured `Retry-After` value for the
  first `rate_limit_for` attempts for each `(run_id, scenario, page)`, then
  returns `200`.
- `permanent` returns `500` on every attempt.
- `resume` returns `500` only for `fail_page`; other pages continue to work.
- `slow` delays the response before returning the normal page.
- `duplicates` repeats the previous page's final ID as the next page's first ID.
- `dom-change` preserves `data-testid` locators while changing CSS classes and
  element nesting.
- `selector-failure` returns normal catalog API data and applies the configured
  locator failure only to its target and page in the browser UI. Presets use
  `[presets.NAME.selector_failure]` with `target`, `mode`, and optional `page` /
  `delay_ms`; `login_button` applies only to page 1.
- `malformed-api` returns status `200` and deliberately violates the normal
  OpenAPI `CatalogPage` response contract. `invalid_json` emits a fixed invalid
  token, `truncated_json` removes the final byte from an otherwise normal page,
  `wrong_content_type` returns a normal JSON page as `text/plain`,
  `missing_fields` omits `items`, and `wrong_field_type` returns `items` as a
  string. Payload construction and truncation points are deterministic.
- `protected=true` on an API request requires the `demo_session` cookie and
  returns `401` with `AUTHENTICATION_REQUIRED` when it is absent.
- `expire_session_after_page=N` implies a protected browser flow. Pages through
  `N` succeed; the first later page expires the session for that `run_id` and
  boundary. API requests then return `401 SESSION_EXPIRED` until valid re-login.
  The browser preserves all scenario parameters and resumes the interrupted
  page. Different `run_id` values remain isolated.
- Invalid constrained values return FastAPI's standard `422` validation body.

Scenario failures expose `detail.code` as one of
`TRANSIENT_CATALOG_FAILURE`, `PERMANENT_CATALOG_FAILURE`, or
`CHECKPOINT_RESUME_FAILURE`. Consumers may assert these codes but not free-form
error wording.

### Browser and demo-login contract

The browser catalog keeps these locators stable through 1.x unless the
`selector-failure` scenario explicitly changes the configured target:
`catalog`, `catalog-item`, `item-name`, `item-price`, `next-page`, and
`catalog-error` (each used as a `data-testid`). The `dom-change` scenario makes
CSS classes and nesting deliberately unstable; consumers should use these
locators, roles, and labels instead.

Protected scenarios accept the configured test credentials, whose defaults are
`demo` / `automation`. A successful login sets `demo_session=authenticated` with
`HttpOnly` and `SameSite=Lax`, then redirects only to a local path. Invalid
credentials return `401`; they must never be reused outside this stand. A
protected `selector-failure` preset carries its target and mode through `/login`
so the `login_button` target is exercised before authentication. A successful
re-login clears an expired state only for the `run_id` and boundary encoded in
the local return URL. `POST /admin/reset` clears all expiry state.

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
files accept documented `ScenarioDefaults` fields, including `malformed_mode`,
`expire_session_after_page`, and the optional nested `selector_failure` table,
and reject unknown fields.

## Contract verification

Every public-contract change requires:

1. an updated behavior test;
2. a reviewed compatibility note and changelog entry;
3. an updated OpenAPI snapshot when HTTP/OpenAPI changes;
4. a semantic-versioning decision;
5. a C# compatibility review before a stable release.
