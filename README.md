# Resilient Automation Test Stand

A deterministic FastAPI target for integration and end-to-end tests of browser
automation workers. It is supporting infrastructure for the parent C# project,
but it already has an independent Python package and CLI boundary.

## Run as a Python package

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
automation-test-stand --port 8080
```

The same server can be started with `python -m app --port 8080`.

## Run with Docker Compose

From the parent repository:

```bash
docker compose up --build demo-site
```

## Stable contract

- `GET /health` reports readiness.
- `GET /catalog` serves a JavaScript-rendered catalog shell.
- `GET /api/catalog` returns deterministic catalog pages.
- `GET|POST /login` provides a predictable authentication form.
- `POST /admin/reset` resets scenario counters.
- `run_id` isolates retry counters between test cases.
- `scenario` selects success, transient, permanent, slow, DOM-change, or duplicate behavior.

## Future extraction to a separate repository

The `test-stand` directory can be split with Git history, then published as:

- a wheel/sdist to an internal package index or PyPI;
- a versioned OCI image to GHCR or another container registry;
- a reusable Compose service pinned by image tag.

Before a public `1.0.0`, rename the internal Python import package from the
generic `app` to `resilient_automation_test_stand`, publish an OpenAPI snapshot,
add semantic-version compatibility tests, and add a deprecation policy for
scenario parameters.

