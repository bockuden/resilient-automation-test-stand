# Changelog

## 1.1.2 - 2026-07-28

### Changed

- Reworked the top of the README around independent PyPI and versioned-container
  quick starts, a copy-ready transient scenario, and clearer product
  positioning for browser automation.
- Added direct links to the Resilience Challenge, C# reference consumer, and
  compatibility contract, plus a concise WireMock and Toxiproxy comparison.
- Moved editable installation and Docker Compose instructions into the
  development-only setup.

### Compatibility

This is a documentation-only release. HTTP behavior, CLI options, scenario
semantics, browser locators, and package requirements are unchanged.

## 1.1.1 - 2026-07-28

### Changed

- Restyled the demo login page to use the catalog's visual system, with a
  responsive dark workspace, accessible labelled fields, focus states, and
  visible fixed demo credentials.
- Extended release verification so clean wheel and Docker runtimes must prove
  health, browser-catalog availability, and the documented transient
  `503`, `503`, `200` sequence with `Retry-After`.

### Compatibility

The login endpoint, form field names, fixed credentials, return-URL handling,
and session-cookie behavior are unchanged.

## 1.1.0 - 2026-07-26

### Changed

- Consolidated the shared `/catalog` and `/api/catalog` query parsing into
  Pydantic query models while preserving the published parameter contract.
- Moved catalog CSS and browser JavaScript into package-local static assets.
  The catalog URL, rendered structure, and stable `data-testid` locators are
  unchanged.

### Compatibility

This release is compatible with 1.0.0 consumers. Existing catalog URLs,
OpenAPI operation IDs, query parameter names, defaults, and constraints remain
stable.

## 1.0.0 - 2026-07-25

### Stable release

- Promotes the externally verified `1.0.0rc1` candidate without API, CLI, or
  scenario changes.
- C# consumer compatibility D2 completed against the exact PyPI/GHCR release
  candidate before this final release.

### Compatibility

The public 1.0 contract introduced in 0.4.0 is now stable. This release is
compatible with 0.4.0 and 1.0.0rc1 consumers; no migration is required.

## 1.0.0rc1 - 2026-07-24

### Release candidate

- Feature freeze for the 1.0 contract published in 0.4.0.
- C# consumer compatibility D1 completed against the exact published 0.4.0
  stand, with no required changes to the stand; 0.5.0 is intentionally skipped.
- This prerelease is intended for exact-version PyPI/GHCR verification and the
  C# D2 compatibility gate. Only release-blocking fixes may follow before 1.0.0.

## 0.4.0 - 2026-07-23

### Added

- Public 1.0 compatibility contract, stable OpenAPI operation IDs, and contract
  tests for retry, pagination, login, and `run_id` isolation.
- Release hardening: non-root container execution, clean-install package checks,
  coverage, Ruff, dependency audit, and release checklist.
- Contributor and security guidance, a browser-automation onboarding path,
  transient-retry GIF, and the reproducible Resilience Challenge.
- GitHub discoverability assets and metadata, including a social preview that
  demonstrates transient `503`, DOM-change, and duplicate scenarios.

### Compatibility

This release preserves the 0.3 public API and CLI behavior. The 1.0 contract
documents which current interfaces are stable and the compatibility guarantees
that apply through 1.0.

## 0.3.0 - 2026-07-22

### Added

- Validated named scenario presets loaded from TOML configuration.
- `--preset`, `--list-presets`, and `--print-url` CLI operations.
- A portable `examples/scenarios.toml` with the documented ten-page and login
  scenarios.

### Compatibility

Built-in defaults and existing query-based URLs are unchanged. An active
preset supplies server defaults, while explicitly supplied query parameters
override only their corresponding fields.

## 0.2.0 - 2026-07-22

### Added

- Cross-platform Python, Docker, browser, and API examples for Windows, Linux,
  and macOS.
- `total_pages` for deterministic catalogs containing between 1 and 20 pages.
- `failure_delay_ms` for delaying transient `503` responses independently of
  the `slow` scenario.
- Preservation of the new parameters through protected-catalog login.
- A development plan for optional named presets and TOML configuration.

### Compatibility

The changes are additive. Existing URLs still expose four pages by default,
and transient failures have no added delay unless `failure_delay_ms` is set.

## 0.1.0 - 2026-07-22

- Initial standalone Python package, CLI, OpenAPI snapshot, Docker image,
  Compose service, CI, and GHCR release workflow.
