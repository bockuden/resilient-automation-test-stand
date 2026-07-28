"""Build concise, version-specific GitHub Release notes from the changelog."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPOSITORY_URL = "https://github.com/bockuden/resilient-automation-test-stand"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPOSITORY_ROOT / "CHANGELOG.md"


def changelog_subsections(changelog: str, version: str) -> dict[str, str]:
    heading = re.compile(rf"^## {re.escape(version)}(?: - .+)?$", re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        raise ValueError(f"CHANGELOG.md has no section for version {version}")

    next_release = re.search(r"^## ", changelog[match.end() :], re.MULTILINE)
    end = match.end() + next_release.start() if next_release else len(changelog)
    release_text = changelog[match.end() : end].strip()

    subsection_matches = list(re.finditer(r"^### (.+)$", release_text, re.MULTILINE))
    subsections: dict[str, str] = {}
    for index, subsection in enumerate(subsection_matches):
        content_start = subsection.end()
        content_end = (
            subsection_matches[index + 1].start()
            if index + 1 < len(subsection_matches)
            else len(release_text)
        )
        subsections[subsection.group(1)] = release_text[content_start:content_end].strip()
    return subsections


def render_release_notes(changelog: str, version: str) -> str:
    subsections = changelog_subsections(changelog, version)
    change_sections = [
        (heading, content)
        for heading, content in subsections.items()
        if heading != "Compatibility" and content
    ]
    if not change_sections:
        raise ValueError(f"CHANGELOG.md version {version} has no change details")

    if len(change_sections) == 1 and change_sections[0][0] == "Changed":
        changed = change_sections[0][1]
    else:
        changed = "\n\n".join(f"### {heading}\n\n{content}" for heading, content in change_sections)

    compatibility = subsections.get(
        "Compatibility",
        "No compatibility or migration notes were recorded for this release.",
    )
    tag = f"v{version}"

    return f"""## What's changed

{changed}

## Install

Requires Python 3.11 or newer.

```bash
python -m pip install resilient-automation-test-stand=={version}
```

## Run

Start the CLI:

```bash
automation-test-stand --port 8080
```

Or run the exact container release:

```bash
docker run --rm -p 8080:8080 \\
  ghcr.io/bockuden/resilient-automation-test-stand:{version}
```

## Try this URL

```text
http://localhost:8080/catalog?scenario=transient&run_id=release-smoke&fail_for=2
```

The first two catalog API requests return `503` with `Retry-After: 1`; the
third succeeds.

## Contract and compatibility

- [Public compatibility contract]({REPOSITORY_URL}/blob/{tag}/docs/compatibility.md)
- [OpenAPI snapshot]({REPOSITORY_URL}/blob/{tag}/docs/api/openapi.json)
- [Resilience Challenge]({REPOSITORY_URL}/blob/{tag}/CHALLENGE.md)

## Upgrade notes

{compatibility}

[Changelog for {version}]({REPOSITORY_URL}/blob/{tag}/CHANGELOG.md)
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build structured GitHub Release notes from CHANGELOG.md."
    )
    parser.add_argument("--version", required=True, help="Package version without the v prefix.")
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    notes = render_release_notes(
        args.changelog.read_text(encoding="utf-8"),
        args.version.removeprefix("v"),
    )
    if args.output:
        args.output.write_text(notes, encoding="utf-8", newline="\n")
        print(f"Wrote {args.output}")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
