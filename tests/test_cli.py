from collections.abc import Iterator
from pathlib import Path

import pytest

import resilient_automation_test_stand.cli as cli
from resilient_automation_test_stand.main import app, configure_scenario_defaults
from resilient_automation_test_stand.presets import ScenarioDefaults


@pytest.fixture(autouse=True)
def reset_server_defaults() -> Iterator[None]:
    configure_scenario_defaults(ScenarioDefaults())
    yield
    configure_scenario_defaults(ScenarioDefaults())


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "scenarios.toml"
    path.write_text(
        """
[presets.ten-pages]
total_pages = 10

[presets.login-delayed-retry]
protected = true
scenario = "transient"
total_pages = 10
fail_for = 2
failure_delay_ms = 1500
""",
        encoding="utf-8",
    )
    return path


def test_cli_lists_presets_in_stable_order(
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["--config", str(config_path), "--list-presets"])

    assert capsys.readouterr().out.splitlines() == [
        "login-delayed-retry",
        "ten-pages",
    ]


def test_cli_prints_reproducible_url(
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(
        [
            "--config",
            str(config_path),
            "--port",
            "9090",
            "--print-url",
            "login-delayed-retry",
        ]
    )

    output = capsys.readouterr().out.strip()
    assert output.startswith("http://localhost:9090/catalog?")
    assert "run_id=login-delayed-retry" in output
    assert "protected=true" in output
    assert "failure_delay_ms=1500" in output


def test_cli_applies_selected_preset_to_server_defaults(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def record_run(application: object, **kwargs: object) -> None:
        calls.append((application, kwargs))

    monkeypatch.setattr(cli.uvicorn, "run", record_run)

    cli.main(
        [
            "--config",
            str(config_path),
            "--preset",
            "login-delayed-retry",
            "--host",
            "0.0.0.0",
            "--port",
            "9090",
        ]
    )

    assert calls == [
        (
            app,
            {"host": "0.0.0.0", "port": 9090, "log_level": "info"},
        )
    ]
    assert app.state.scenario_defaults.scenario == "transient"
    assert app.state.scenario_defaults.protected is True
    assert app.state.scenario_defaults.total_pages == 10


def test_cli_rejects_unknown_preset(
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", str(config_path), "--preset", "missing"])

    assert error.value.code == 2
    assert "unknown preset 'missing'" in capsys.readouterr().err


def test_cli_requires_config_for_preset_operations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["--list-presets"])

    assert error.value.code == 2
    assert "--config is required" in capsys.readouterr().err
