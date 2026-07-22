# ADR 0001: Use FastAPI for the deterministic browser target

- Status: accepted
- Date: 2026-07-16

## Context

Browser automation workers need repeatable integration and end-to-end tests
without depending on third-party websites. The target must simulate
browser-specific behavior and failures while remaining small and portable.

## Decision

Use a Python FastAPI service as the test stand and distribute it as both a
Python package and a container image. Scenario behavior is selected by query
parameters, and request counters are isolated by `run_id`.

## Consequences

- Tests are deterministic and can run locally or in CI without external sites.
- Consumers can use the stand from Python, Docker, or Docker Compose.
- In-memory counters are sufficient for a single-container test stand.
- The service is intended for testing, not horizontal scaling or production.
