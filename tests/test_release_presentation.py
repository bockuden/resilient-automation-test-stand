import re
import tomllib
from pathlib import Path

import pytest

from scripts.build_release_notes import changelog_subsections, render_release_notes

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_release_notes_include_runnable_versioned_sections() -> None:
    changelog = """
# Changelog

## 2.3.4 - 2026-07-28

### Changed

- Added a deterministic example.

### Compatibility

No public contract changes.

## 2.3.3 - 2026-07-27
"""

    notes = render_release_notes(changelog, "2.3.4")

    assert "## What's changed" in notes
    assert "## Install" in notes
    assert "resilient-automation-test-stand==2.3.4" in notes
    assert "## Run" in notes
    assert "resilient-automation-test-stand:2.3.4" in notes
    assert "## Try this URL" in notes
    assert "## Contract and compatibility" in notes
    assert "/blob/v2.3.4/docs/compatibility.md" in notes
    assert "## Upgrade notes" in notes
    assert "No public contract changes." in notes


def test_release_notes_require_matching_change_details() -> None:
    with pytest.raises(ValueError, match="no section for version 9.9.9"):
        changelog_subsections("# Changelog\n", "9.9.9")

    changelog = "## 9.9.9\n\n### Compatibility\n\nCompatible."
    with pytest.raises(ValueError, match="has no change details"):
        render_release_notes(changelog, "9.9.9")


def test_current_project_version_can_render_from_the_real_changelog() -> None:
    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]

    notes = render_release_notes(changelog, version)

    assert f"resilient-automation-test-stand=={version}" in notes
    assert f"resilient-automation-test-stand:{version}" in notes
    assert "## Upgrade notes" in notes


def test_readme_links_and_images_are_safe_for_pypi() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    destinations = re.findall(r"!?\[[^\]]*]\(([^)]+)\)", readme)

    assert destinations
    assert all(destination.startswith("https://") for destination in destinations)
    assert (
        "https://raw.githubusercontent.com/bockuden/"
        "resilient-automation-test-stand/main/docs/assets/transient-retry.gif" in destinations
    )
