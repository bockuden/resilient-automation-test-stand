# Changelog

## 0.2.0 - Unreleased

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
