# Release checklist

Use this checklist before creating a release tag. A tag is a publication action,
not a substitute for verifying the release process.

## One-time publisher setup

Before the first PyPI publication, configure a PyPI Trusted Publisher for:

- owner: `bockuden`;
- repository: `resilient-automation-test-stand`;
- workflow filename: `release.yml` (the file is located at `.github/workflows/release.yml`);
- GitHub environment: `pypi`.

Create the GitHub `pypi` environment and, where practical, protect it with a
required reviewer. The workflow uses OIDC and must not receive a long-lived
PyPI API token. See the official
[PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/).

## Per-release checks

- The working tree is clean and the intended commit is on `main`.
- `pyproject.toml`, package metadata, and changelog contain the target version.
- `python -m pytest` passes on supported Python versions in CI.
- `python scripts/export_openapi.py --check` passes.
- `python -m build` and `twine check dist/*` pass.
- Clean virtual environments install and run both the wheel and sdist.
- A clean wheel installation starts through `automation-test-stand`, returns
  `{"status":"ok"}` from `/health`, serves the browser catalog, and produces
  the expected transient sequence: `503`, `503`, then `200`, with
  `Retry-After: 1` on both failures.
- The Docker image starts as `appuser`, serves `/health` with a read-only
  filesystem, contains no test dependencies or source tests, serves the browser
  catalog, and produces the same transient sequence as the wheel.
- The tag follows the release policy and matches the package version as
  `v<package-version>`.
- Any public-contract change has an updated OpenAPI snapshot, compatibility
  note, changelog entry, and C# compatibility review.

## Publication result

Pushing a verified tag runs these jobs in order:

1. verify and build the Python distributions once;
2. publish those verified distributions to PyPI using OIDC;
3. publish the container to GHCR after the build succeeds;
4. create a GitHub Release with the verified wheel and sdist.

The Docker metadata action derives version tags from PEP 440 release tags. The
default `latest` tag is emitted only for a final release, not for a pre-release.
Do not use `latest` for C# compatibility validation; pin an exact image version.

## Post-publication smoke checks

Run these checks from a directory that is not a repository checkout. Replace
`<version>` with the exact final version; never use an unpinned package or
container reference for release verification.

### Published Python package

```bash
python -m venv .venv-stand
# Activate the virtual environment for the current shell.
python -m pip install resilient-automation-test-stand==<version>
automation-test-stand --port 8080
```

Verify `/health`, open the browser catalog, and request the API URL below three
times. The responses must be `503`, `503`, and `200`; both failures must contain
`Retry-After: 1`.

```text
http://localhost:8080/api/catalog?scenario=transient&run_id=release-pypi&fail_for=2&page=1
```

### Published container

```bash
docker run --rm -p 8080:8080 \
  ghcr.io/bockuden/resilient-automation-test-stand:<version>
```

Repeat the health, browser-catalog, and transient-sequence checks with a new
`run_id`. Confirm that the image OCI labels contain the same version and source
repository.

### Canonical release locations

- PyPI: `https://pypi.org/project/resilient-automation-test-stand/<version>/`
- GitHub Release:
  `https://github.com/bockuden/resilient-automation-test-stand/releases/tag/v<version>`
- Container package:
  `https://github.com/bockuden/resilient-automation-test-stand/pkgs/container/resilient-automation-test-stand`
- Image:
  `ghcr.io/bockuden/resilient-automation-test-stand:<version>`

The PyPI release, GitHub Release, wheel, sdist, image tag, and OCI
`org.opencontainers.image.version` label must all name the same version.

## Source distribution contents

The source distribution intentionally includes the tests and public documents.
They let downstream users inspect and verify the same contract that produced the
release. The runtime Docker image remains separate and excludes test dependencies
and the `tests/` source directory.
