import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from resilient_automation_test_stand.presets import (
    AuthConfig,
    PresetConfigError,
    ScenarioDefaults,
    SelectorConfig,
    SelectorFailureConfig,
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
    assert document.auth == AuthConfig()
    assert document.resolved_auth.username == "demo"
    assert document.resolved_auth.password == "automation"
    assert document.selectors == SelectorConfig()


def test_custom_selector_tokens_load_from_toml(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "selectors.toml",
        """
[selectors]
username = "account-name"
password = "account-secret"
login_button = "submit-login"
catalog = "product-list"
item = "product-card"
item_name = "product-title"
item_price = "product-cost"
next_page = "page-forward"

[presets.default]
""",
    )

    assert load_preset_document(path).selectors == SelectorConfig(
        username="account-name",
        password="account-secret",
        login_button="submit-login",
        catalog="product-list",
        item="product-card",
        item_name="product-title",
        item_price="product-cost",
        next_page="page-forward",
    )


@pytest.mark.parametrize(
    ("mode", "target"),
    [
        ("missing", "next_page"),
        ("changed", "item"),
        ("multiple", "login_button"),
        ("delayed", "next_page"),
        ("hidden", "item"),
        ("disabled", "login_button"),
    ],
)
def test_selector_failure_modes_load_from_preset(
    tmp_path: Path,
    mode: str,
    target: str,
) -> None:
    page = 1 if target == "login_button" else 2
    path = write_config(
        tmp_path / "selector-failures.toml",
        f"""
[presets.selector-test]
scenario = "selector-failure"

[presets.selector-test.selector_failure]
target = "{target}"
mode = "{mode}"
page = {page}
""",
    )

    failure = load_preset_document(path).presets["selector-test"].selector_failure

    assert failure == SelectorFailureConfig(target=target, mode=mode, page=page)


def test_rate_limit_preset_loads_bounded_defaults(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "rate-limit.toml",
        """
[presets.rate-limited]
scenario = "rate-limit"
rate_limit_for = 3
retry_after_seconds = 12
""",
    )

    assert load_preset_document(path).presets["rate-limited"] == ScenarioDefaults(
        scenario="rate-limit",
        rate_limit_for=3,
        retry_after_seconds=12,
    )


def test_composite_event_preset_loads_ordered_typed_events(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "composite.toml",
        """
[presets.nightmare]
protected = true
total_pages = 10

[[presets.nightmare.events]]
page = 2
type = "http_error"
status = 503
attempts = 2

[[presets.nightmare.events]]
page = 4
type = "duplicate_items"

[[presets.nightmare.events]]
page = 5
type = "expire_session"

[[presets.nightmare.events]]
page = 7
type = "selector_change"
target = "next_page"

[[presets.nightmare.events]]
page = 9
type = "delay"
delay_ms = 3000
""",
    )

    preset = load_preset_document(path).presets["nightmare"]

    assert [event.type for event in preset.events] == [
        "http_error",
        "duplicate_items",
        "expire_session",
        "selector_change",
        "delay",
    ]
    assert [event.page for event in preset.events] == [2, 4, 5, 7, 9]
    assert preset.events[0].model_dump() == {
        "type": "http_error",
        "page": 2,
        "status": 503,
        "attempts": 2,
    }


@pytest.mark.parametrize(
    "mode",
    [
        "invalid_json",
        "truncated_json",
        "wrong_content_type",
        "missing_fields",
        "wrong_field_type",
    ],
)
def test_malformed_api_modes_load_from_preset(tmp_path: Path, mode: str) -> None:
    path = write_config(
        tmp_path / "malformed-api.toml",
        f"""
[presets.broken-upstream]
scenario = "malformed-api"
malformed_mode = "{mode}"
""",
    )

    assert load_preset_document(path).presets["broken-upstream"] == ScenarioDefaults(
        scenario="malformed-api",
        malformed_mode=mode,
    )


def test_session_expiry_preset_loads_deterministic_page_boundary(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "session-expiry.toml",
        """
[presets.session-expiry]
scenario = "success"
protected = true
expire_session_after_page = 2
""",
    )

    assert load_preset_document(path).presets["session-expiry"] == ScenarioDefaults(
        scenario="success",
        protected=True,
        expire_session_after_page=2,
    )


def test_custom_auth_credentials_load_from_toml(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "scenarios.toml",
        """
[auth]
username = "custom-user"
password = "custom-password"

[presets.default]
""",
    )

    document = load_preset_document(path)

    assert document.auth.username == "custom-user"
    assert document.auth.password == "custom-password"
    assert document.resolved_auth.username == "custom-user"
    assert document.resolved_auth.password == "custom-password"


@pytest.mark.parametrize(
    ("field", "environment_name", "literal", "environment_value", "expected"),
    [
        ("username", "TEST_USERNAME", "literal-user", "env-user", "env-user"),
        ("password", "TEST_PASSWORD", "literal-password", "env-password", "env-password"),
    ],
)
def test_auth_environment_value_overrides_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    environment_name: str,
    literal: str,
    environment_value: str,
    expected: str,
) -> None:
    monkeypatch.setenv(environment_name, environment_value)
    path = write_config(
        tmp_path / "scenarios.toml",
        f"""
[auth]
{field} = "{literal}"
{field}_env = "{environment_name}"

[presets.default]
""",
    )

    document = load_preset_document(path)

    assert getattr(document.resolved_auth, field) == expected


def test_missing_auth_environment_variable_falls_back_to_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_TEST_USERNAME", raising=False)
    path = write_config(
        tmp_path / "scenarios.toml",
        """
[auth]
username = "literal-user"
username_env = "MISSING_TEST_USERNAME"

[presets.default]
""",
    )

    assert load_preset_document(path).resolved_auth.username == "literal-user"


def test_auth_environment_values_are_resolved_once_during_config_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONCE_TEST_USERNAME", "first-value")
    path = write_config(
        tmp_path / "scenarios.toml",
        """
[auth]
username_env = "ONCE_TEST_USERNAME"

[presets.default]
""",
    )

    auth = load_preset_document(path).resolved_auth
    monkeypatch.setenv("ONCE_TEST_USERNAME", "second-value")

    assert auth.username == "first-value"


def test_empty_resolved_environment_credential_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMPTY_TEST_PASSWORD", "")
    path = write_config(
        tmp_path / "scenarios.toml",
        """
[auth]
password_env = "EMPTY_TEST_PASSWORD"

[presets.default]
""",
    )

    with pytest.raises(PresetConfigError, match="EMPTY_TEST_PASSWORD.*empty credential"):
        load_preset_document(path)


@pytest.mark.parametrize(
    "content",
    [
        "[presets.Bad_Name]\ntotal_pages = 10\n",
        "[presets.too-many]\ntotal_pages = 21\n",
        "[presets.unknown]\nextra = true\n",
        "[auth]\nunknown = 'value'\n[presets.default]\n",
        "[presets.wrong-type]\ntotal_pages = '10'\n",
        "[auth]\nusername = ''\n[presets.default]\n",
        "[auth]\nusername_env = 'NOT-VALID'\n[presets.default]\n",
        "[selectors]\nitem = '[data-secret=\"x\"]'\n[presets.default]\n",
        "[selectors]\nunknown = 'token'\n[presets.default]\n",
        '[presets.invalid.selector_failure]\ntarget = "other"\nmode = "missing"\n',
        '[presets.invalid.selector_failure]\ntarget = "item"\nmode = "random"\n',
        '[presets.invalid.selector_failure]\ntarget = "next_page"\nmode = "delayed"\ndelay_ms = 5001\n',
        '[presets.invalid.selector_failure]\ntarget = "login_button"\nmode = "hidden"\npage = 2\n',
        "[presets.rate-limit]\nrate_limit_for = -1\n",
        "[presets.rate-limit]\nrate_limit_for = 11\n",
        "[presets.rate-limit]\nretry_after_seconds = 301\n",
        '[presets.malformed]\nscenario = "malformed-api"\nmalformed_mode = "random"\n',
        "[presets.session-expiry]\nexpire_session_after_page = 0\n",
        "[presets.session-expiry]\nexpire_session_after_page = 21\n",
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "unknown"\npage = 2\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "http_error"\npage = 2\nstatus = 500\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "delay"\npage = 2\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "duplicate_items"\npage = 1\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "selector_change"\npage = 2\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "delay"\npage = 5\ndelay_ms = 10\n',
        '[presets.invalid]\nscenario = "transient"\n[[presets.invalid.events]]\ntype = "delay"\npage = 2\ndelay_ms = 10\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "delay"\npage = 2\ndelay_ms = 10\n[[presets.invalid.events]]\ntype = "delay"\npage = 2\ndelay_ms = 20\n',
        '[presets.invalid]\ntotal_pages = 4\n[[presets.invalid.events]]\ntype = "expire_session"\npage = 2\n[[presets.invalid.events]]\ntype = "expire_session"\npage = 3\n',
        '[presets.invalid]\ntotal_pages = 4\nexpire_session_after_page = 2\n[[presets.invalid.events]]\ntype = "expire_session"\npage = 3\n',
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


def test_preset_url_flattens_selector_failure_settings() -> None:
    url = preset_url(
        "selector-missing",
        ScenarioDefaults(
            scenario="selector-failure",
            selector_failure=SelectorFailureConfig(target="next_page", mode="missing", page=2),
        ),
        "http://localhost:8080/catalog",
    )

    query = parse_qs(urlsplit(url).query)
    assert query["scenario"] == ["selector-failure"]
    assert query["selector_failure_target"] == ["next_page"]
    assert query["selector_failure_mode"] == ["missing"]
    assert query["selector_failure_page"] == ["2"]
    assert query["selector_failure_delay_ms"] == ["500"]


def test_preset_url_serializes_composite_events_as_portable_json() -> None:
    defaults = ScenarioDefaults.model_validate(
        {
            "total_pages": 5,
            "events": [
                {"type": "http_error", "page": 2, "status": 503, "attempts": 2},
                {"type": "delay", "page": 2, "delay_ms": 250},
                {"type": "duplicate_items", "page": 4},
            ],
        }
    )

    query = parse_qs(
        urlsplit(preset_url("composite", defaults, "http://localhost:8080/catalog")).query
    )

    assert json.loads(query["events_json"][0]) == [
        {"type": "http_error", "page": 2, "status": 503, "attempts": 2},
        {"type": "delay", "page": 2, "delay_ms": 250},
        {"type": "duplicate_items", "page": 4},
    ]


def test_rate_limit_preset_url_contains_overridable_rate_limit_values() -> None:
    url = preset_url(
        "rate-limited",
        ScenarioDefaults(
            scenario="rate-limit",
            rate_limit_for=3,
            retry_after_seconds=12,
        ),
        "http://localhost:8080/catalog",
    )

    query = parse_qs(urlsplit(url).query)
    assert query["scenario"] == ["rate-limit"]
    assert query["rate_limit_for"] == ["3"]
    assert query["retry_after_seconds"] == ["12"]
