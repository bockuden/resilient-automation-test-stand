from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from resilient_automation_test_stand.presets import (
    PresetConfigError,
    ScenarioDefaults,
    load_preset_document,
    preset_url,
)


def write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_partial_preset_inherits_builtin_defaults(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "scenarios.toml",
        """
[presets.ten-pages]
total_pages = 10
""",
    )

    document = load_preset_document(path)

    assert document.presets["ten-pages"] == ScenarioDefaults(total_pages=10)


@pytest.mark.parametrize(
    "content",
    [
        "[presets.Bad_Name]\ntotal_pages = 10\n",
        "[presets.too-many]\ntotal_pages = 21\n",
        "[presets.unknown]\nextra = true\n",
        "[presets.wrong-type]\ntotal_pages = '10'\n",
        "presets = 'not a table'\n",
    ],
)
def test_invalid_preset_config_has_actionable_error(
    tmp_path: Path,
    content: str,
) -> None:
    path = write_config(tmp_path / "invalid.toml", content)

    with pytest.raises(PresetConfigError, match="invalid preset config"):
        load_preset_document(path)


def test_missing_config_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(PresetConfigError, match="cannot read preset config"):
        load_preset_document(tmp_path / "missing.toml")


def test_preset_url_contains_complete_portable_scenario() -> None:
    url = preset_url(
        "login-retry",
        ScenarioDefaults(
            scenario="transient",
            protected=True,
            total_pages=10,
            fail_for=2,
            failure_delay_ms=1500,
        ),
        "http://localhost:9090/catalog?source=cli",
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == ("http://localhost:9090/catalog")
    assert query["source"] == ["cli"]
    assert query["run_id"] == ["login-retry"]
    assert query["scenario"] == ["transient"]
    assert query["protected"] == ["true"]
    assert query["total_pages"] == ["10"]
    assert query["fail_for"] == ["2"]
    assert query["failure_delay_ms"] == ["1500"]
