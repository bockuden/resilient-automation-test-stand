# ADR 0002: Distribute the test stand independently

- Status: accepted
- Date: 2026-07-22

## Context

The deterministic target is useful to automation projects regardless of their
implementation language. Consumers should not need to clone or build a browser
worker in order to exercise retry, pagination, authentication, DOM drift,
delays, cancellation, and duplicate handling.

## Decision

Maintain the stand in its own repository with an independently versioned Python
package, CLI, OpenAPI snapshot, tests, Docker image, Compose definition, and
release cycle. Publish versioned images to
`ghcr.io/bockuden/resilient-automation-test-stand`.

Treat scenario names, endpoint parameters, and response shapes as a public
contract. API changes require an updated OpenAPI snapshot, release notes, a
package version change, and a compatibility review.

## Consequences

- Python and OCI consumers can pin a released version.
- Worker repositories test integration against an explicit stand version.
- The stand can evolve on its own schedule.
- Releases must keep the package, API, and image versions aligned.
