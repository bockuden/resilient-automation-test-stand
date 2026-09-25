from collections.abc import Iterator
from pathlib import Path

import pytest

import resilient_automation_test_stand.cli as cli
from resilient_automation_test_stand.main import (
    app,
    configure_auth,
    configure_scenario_defaults,
)
from resilient_automation_test_stand.presets import ResolvedAuth, ScenarioDefaults


@pytest.fixture(autouse=True)
def reset_server_defaults() -> Iterator[None]:
    configure_scenario_defaults(ScenarioDefaults())
    configure_auth(ResolvedAuth())
    yield
    configure_scenario_defaults(ScenarioDefaults())
    configure_auth(ResolvedAuth())


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


def test_cli_config_without_preset_applies_global_auth(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path.write_text(
        """
[auth]
username = "config-user"
password = "config-password"

[presets.default]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_args, **_kwargs: None)

    cli.main(["--config", str(config_path)])

    assert app.state.auth == ResolvedAuth(username="config-user", password="config-password")
    assert app.state.scenario_defaults == ScenarioDefaults()


def test_cli_config_and_preset_apply_global_auth_and_scenario(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path.write_text(
        """
[auth]
username = "combined-user"
password = "combined-password"

[presets.login-delayed-retry]
protected = true
scenario = "transient"
total_pages = 10
fail_for = 2
failure_delay_ms = 1500
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_args, **_kwargs: None)

    cli.main(["--config", str(config_path), "--preset", "login-delayed-retry"])

    assert app.state.auth == ResolvedAuth(
        username="combined-user",
        password="combined-password",
    )
    assert app.state.scenario_defaults.scenario == "transient"
    assert app.state.scenario_defaults.protected is True
    assert app.state.scenario_defaults.total_pages == 10


def test_print_url_does_not_expose_auth_or_environment_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("URL_TEST_USERNAME", "env-secret-user")
    monkeypatch.setenv("URL_TEST_PASSWORD", "env-secret-password")
    path = tmp_path / "auth.toml"
    path.write_text(
        """
[auth]
username = "literal-secret-user"
password = "literal-secret-password"
username_env = "URL_TEST_USERNAME"
password_env = "URL_TEST_PASSWORD"

[presets.login]
protected = true
""",
        encoding="utf-8",
    )

    cli.main(["--config", str(path), "--print-url", "login"])

    output = capsys.readouterr().out
    for secret in (
        "env-secret-user",
        "env-secret-password",
        "literal-secret-user",
        "literal-secret-password",
        "URL_TEST_USERNAME",
        "URL_TEST_PASSWORD",
    ):
        assert secret not in output


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
