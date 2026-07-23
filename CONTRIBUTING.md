# Contributing

Issues and pull requests are welcome when they add a reproducible browser
automation use case or improve the documented public contract.

Before opening a pull request:

1. Explain the consumer behavior being tested and the deterministic scenario it
   needs.
2. Keep HTTP, CLI, and stable locator changes backward compatible, or document
   the migration in `CHANGELOG.md` and `docs/compatibility.md`.
3. Run `python -m pip install -e '.[dev]'`, `python -m pytest`, `ruff check .`,
   `ruff format --check .`, and `python scripts/export_openapi.py --check`.
4. Update the OpenAPI snapshot when a public endpoint or model changes.

Do not add production crawling features, anti-bot claims, or a scenario unless
it has a clear consumer-side resilience use case.
