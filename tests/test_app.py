from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

import resilient_automation_test_stand.main as app_module
from resilient_automation_test_stand.main import (
    app,
    configure_auth,
    configure_scenario_defaults,
    configure_selectors,
)
from resilient_automation_test_stand.presets import (
    ResolvedAuth,
    ScenarioDefaults,
    SelectorConfig,
    SelectorFailureConfig,
    load_preset_document,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    configure_scenario_defaults(ScenarioDefaults())
    configure_auth(ResolvedAuth())
    configure_selectors(SelectorConfig())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        await test_client.post("/admin/reset")
        try:
            yield test_client
        finally:
            configure_scenario_defaults(ScenarioDefaults())
            configure_auth(ResolvedAuth())
            configure_selectors(SelectorConfig())


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.anyio
async def test_catalog_page_loads_dynamic_shell(client: AsyncClient) -> None:
    response = await client.get("/catalog?scenario=success&run_id=test")
    assert response.status_code == 200
    assert 'data-testid="catalog"' in response.text
    assert 'href="/static/catalog.css"' in response.text
    assert 'src="/static/catalog.js"' in response.text
    assert 'id="catalog-config"' in response.text


@pytest.mark.anyio
async def test_catalog_static_assets_are_served(client: AsyncClient) -> None:
    stylesheet = await client.get("/static/catalog.css")
    script = await client.get("/static/catalog.js")

    assert stylesheet.status_code == 200
    assert ".product-card," in stylesheet.text
    assert script.status_code == 200
    assert "async function loadPage(page)" in script.text


@pytest.mark.anyio
async def test_transient_scenario_fails_twice_then_recovers(client: AsyncClient) -> None:
    url = "/api/catalog?scenario=transient&run_id=retry-case&page=1&fail_for=2"
    assert (await client.get(url)).status_code == 503
    assert (await client.get(url)).status_code == 503
    recovered = await client.get(url)
    assert recovered.status_code == 200
    assert recovered.json()["attempt"] == 3


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "expected_content_type", "expected_body"),
    [
        ("invalid_json", "application/json", '{"page":20,"items":[INVALID]}'),
        (
            "truncated_json",
            "application/json",
            '{"page":20,"total_pages":1,"items":[],"scenario":"malformed-api","attempt":1',
        ),
        (
            "wrong_content_type",
            "text/plain",
            '{"page":20,"total_pages":1,"items":[],"scenario":"malformed-api","attempt":1}',
        ),
        (
            "missing_fields",
            "application/json",
            '{"page":20,"total_pages":1,"scenario":"malformed-api","attempt":1}',
        ),
        (
            "wrong_field_type",
            "application/json",
            '{"page":20,"total_pages":1,"items":"not-a-list",'
            '"scenario":"malformed-api","attempt":1}',
        ),
    ],
)
async def test_malformed_api_modes_return_exact_deterministic_responses(
    client: AsyncClient,
    mode: str,
    expected_content_type: str,
    expected_body: str,
) -> None:
    url = (
        "/api/catalog?scenario=malformed-api&run_id=malformed-replay&page=20"
        f"&total_pages=1&malformed_mode={mode}"
    )

    first = await client.get(url)
    await client.post("/admin/reset")
    replay = await client.get(url)

    assert first.status_code == replay.status_code == 200
    assert first.headers["content-type"] == replay.headers["content-type"] == expected_content_type
    assert first.text == replay.text == expected_body


@pytest.mark.anyio
async def test_malformed_api_query_rejects_unknown_mode(client: AsyncClient) -> None:
    response = await client.get(
        "/api/catalog?scenario=malformed-api&malformed_mode=random_truncation"
    )

    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario", "extra_query", "expected_status", "expected_body"),
    [
        (
            "success",
            "&total_pages=1&page=20",
            200,
            '{"page":20,"total_pages":1,"items":[],"scenario":"success","attempt":1}',
        ),
        (
            "transient",
            "&fail_for=1",
            503,
            '{"detail":{"code":"TRANSIENT_CATALOG_FAILURE","attempt":1}}',
        ),
        (
            "permanent",
            "",
            500,
            '{"detail":{"code":"PERMANENT_CATALOG_FAILURE","attempt":1}}',
        ),
    ],
)
async def test_existing_api_responses_remain_unchanged(
    client: AsyncClient,
    scenario: str,
    extra_query: str,
    expected_status: int,
    expected_body: str,
) -> None:
    response = await client.get(
        f"/api/catalog?scenario={scenario}&run_id=unchanged-{scenario}{extra_query}"
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"] == "application/json"
    assert response.text == expected_body


@pytest.mark.anyio
async def test_rate_limit_scenario_returns_exactly_n_429s_then_recovers(
    client: AsyncClient,
) -> None:
    url = (
        "/api/catalog?scenario=rate-limit&run_id=rate-limit-retry&page=1"
        "&rate_limit_for=2&retry_after_seconds=7"
    )

    first = await client.get(url)
    second = await client.get(url)
    recovered = await client.get(url)

    assert first.status_code == second.status_code == 429
    assert first.headers["retry-after"] == second.headers["retry-after"] == "7"
    assert first.json()["detail"] == {"code": "RATE_LIMITED", "attempt": 1}
    assert second.json()["detail"] == {"code": "RATE_LIMITED", "attempt": 2}
    assert recovered.status_code == 200
    assert recovered.json()["attempt"] == 3


@pytest.mark.anyio
async def test_rate_limit_counters_are_isolated_by_run_id(client: AsyncClient) -> None:
    first_run = await client.get("/api/catalog?scenario=rate-limit&run_id=first&page=1")
    first_run_recovered = await client.get("/api/catalog?scenario=rate-limit&run_id=first&page=1")
    second_run = await client.get("/api/catalog?scenario=rate-limit&run_id=second&page=1")

    assert first_run.status_code == second_run.status_code == 429
    assert first_run_recovered.status_code == 429
    assert first_run.json()["detail"]["attempt"] == 1
    assert first_run_recovered.json()["detail"]["attempt"] == 2
    assert second_run.json()["detail"]["attempt"] == 1


@pytest.mark.anyio
async def test_rate_limit_query_overrides_preset_defaults(client: AsyncClient) -> None:
    configure_scenario_defaults(
        ScenarioDefaults(scenario="rate-limit", rate_limit_for=3, retry_after_seconds=15)
    )
    url = "/api/catalog?run_id=rate-limit-overrides&rate_limit_for=1&retry_after_seconds=9"

    limited = await client.get(url)
    recovered = await client.get(url)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "9"
    assert recovered.status_code == 200


@pytest.mark.anyio
async def test_admin_reset_restarts_rate_limit_counter(client: AsyncClient) -> None:
    url = "/api/catalog?scenario=rate-limit&run_id=rate-limit-reset&page=1&rate_limit_for=1"
    assert (await client.get(url)).status_code == 429

    reset = await client.post("/admin/reset")
    first_after_reset = await client.get(url)

    assert reset.json() == {"clearedCounters": 1}
    assert first_after_reset.status_code == 429
    assert first_after_reset.json()["detail"]["attempt"] == 1


@pytest.mark.anyio
async def test_rate_limit_query_rejects_out_of_range_values(client: AsyncClient) -> None:
    too_many_failures = await client.get("/api/catalog?scenario=rate-limit&rate_limit_for=11")
    too_long_retry_after = await client.get(
        "/api/catalog?scenario=rate-limit&retry_after_seconds=301"
    )

    assert too_many_failures.status_code == 422
    assert too_long_retry_after.status_code == 422


@pytest.mark.anyio
async def test_catalog_shell_passes_rate_limit_defaults_to_browser_runtime(
    client: AsyncClient,
) -> None:
    configure_scenario_defaults(
        ScenarioDefaults(scenario="rate-limit", rate_limit_for=4, retry_after_seconds=9)
    )

    shell = await client.get("/catalog?run_id=browser-rate-limit")
    script = await client.get("/static/catalog.js")

    assert '"rateLimitFor": 4' in shell.text
    assert '"retryAfterSeconds": 9' in shell.text
    assert "rate_limit_for: config.rateLimitFor" in script.text
    assert "retry_after_seconds: config.retryAfterSeconds" in script.text


@pytest.mark.anyio
async def test_protected_rate_limit_settings_survive_login_redirect(client: AsyncClient) -> None:
    configure_scenario_defaults(
        ScenarioDefaults(
            scenario="rate-limit",
            protected=True,
            rate_limit_for=3,
            retry_after_seconds=8,
        )
    )

    response = await client.get("/catalog?run_id=protected-rate-limit", follow_redirects=False)
    next_url = parse_qs(urlsplit(response.headers["location"]).query)["next_url"][0]

    assert response.status_code == 303
    assert "scenario=rate-limit" in next_url
    assert "rate_limit_for=3" in next_url
    assert "retry_after_seconds=8" in next_url


@pytest.mark.anyio
async def test_run_id_isolates_transient_attempt_counters(client: AsyncClient) -> None:
    first_run = await client.get("/api/catalog?scenario=transient&run_id=first&page=1&fail_for=1")
    second_run = await client.get("/api/catalog?scenario=transient&run_id=second&page=1&fail_for=1")

    assert first_run.status_code == 503
    assert second_run.status_code == 503
    assert first_run.json()["detail"] == {
        "code": "TRANSIENT_CATALOG_FAILURE",
        "attempt": 1,
    }
    assert first_run.headers["retry-after"] == "1"


@pytest.mark.anyio
async def test_catalog_api_rejects_page_outside_public_range(client: AsyncClient) -> None:
    response = await client.get("/api/catalog?page=21")

    assert response.status_code == 422


def test_openapi_uses_stable_public_operation_ids() -> None:
    paths = app.openapi()["paths"]

    assert paths["/health"]["get"]["operationId"] == "get_health"
    assert paths["/catalog"]["get"]["operationId"] == "get_catalog_shell"
    assert paths["/api/catalog"]["get"]["operationId"] == "get_catalog_page"
    assert paths["/login"]["post"]["operationId"] == "submit_demo_login"


def test_openapi_preserves_catalog_query_parameter_contract() -> None:
    paths = app.openapi()["paths"]

    catalog_parameters = {
        parameter["name"]: parameter
        for parameter in paths["/catalog"]["get"]["parameters"]
        if parameter["in"] == "query"
    }
    api_parameters = {
        parameter["name"]: parameter
        for parameter in paths["/api/catalog"]["get"]["parameters"]
        if parameter["in"] == "query"
    }

    common_parameters = {
        "scenario",
        "run_id",
        "fail_for",
        "delay_ms",
        "failure_delay_ms",
        "fail_page",
        "total_pages",
        "selector_failure_target",
        "selector_failure_mode",
        "selector_failure_page",
        "selector_failure_delay_ms",
        "rate_limit_for",
        "retry_after_seconds",
        "malformed_mode",
    }
    assert set(catalog_parameters) == common_parameters | {"protected"}
    assert set(api_parameters) == common_parameters | {"page"}
    assert catalog_parameters["run_id"]["schema"]["default"] == "manual"
    assert api_parameters["page"]["schema"] == {
        "type": "integer",
        "maximum": 20,
        "minimum": 1,
        "description": "One-based catalog page to fetch.",
        "default": 1,
        "title": "Page",
    }
    assert catalog_parameters["protected"]["schema"]["description"] == (
        "Require login with configured credentials before serving the catalog shell."
    )


@pytest.mark.anyio
async def test_duplicate_scenario_repeats_previous_page_item(client: AsyncClient) -> None:
    page_one = (await client.get("/api/catalog?scenario=duplicates&run_id=dupes&page=1")).json()
    page_two = (await client.get("/api/catalog?scenario=duplicates&run_id=dupes&page=2")).json()
    assert page_one["items"][-1]["id"] == page_two["items"][0]["id"]


@pytest.mark.anyio
async def test_protected_catalog_requires_login(client: AsyncClient) -> None:
    response = await client.get(
        "/catalog?scenario=slow&run_id=protected-case&delay_ms=2500&failure_delay_ms=750"
        "&fail_page=4&total_pages=10&protected=true",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    next_url = parse_qs(urlsplit(response.headers["location"]).query)["next_url"][0]
    assert "scenario=slow" in next_url
    assert "run_id=protected-case" in next_url
    assert "delay_ms=2500" in next_url
    assert "failure_delay_ms=750" in next_url
    assert "fail_page=4" in next_url
    assert "total_pages=10" in next_url
    assert "protected=true" in next_url


@pytest.mark.anyio
async def test_login_sets_session_cookie(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "demo", "password": "automation", "next_url": "/catalog?protected=true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.cookies["demo_session"] == "authenticated"


@pytest.mark.anyio
async def test_wrong_default_credentials_return_unauthorized(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "demo", "password": "wrong", "next_url": "/catalog"},
        follow_redirects=False,
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_custom_credentials_work_and_default_credentials_fail(client: AsyncClient) -> None:
    configure_auth(ResolvedAuth(username="custom-user", password="custom-password"))

    old_credentials = await client.post(
        "/login",
        data={"username": "demo", "password": "automation", "next_url": "/catalog"},
        follow_redirects=False,
    )
    custom_credentials = await client.post(
        "/login",
        data={
            "username": "custom-user",
            "password": "custom-password",
            "next_url": "/catalog?protected=true",
        },
        follow_redirects=False,
    )

    assert old_credentials.status_code == 401
    assert custom_credentials.status_code == 303
    assert custom_credentials.headers["location"] == "/catalog?protected=true"
    assert custom_credentials.cookies["demo_session"] == "authenticated"


@pytest.mark.anyio
async def test_login_form_does_not_render_configured_credentials(client: AsyncClient) -> None:
    configure_auth(ResolvedAuth(username="env-secret-user", password="env-secret-password"))

    response = await client.get("/login")

    assert response.status_code == 200
    assert "Use the credentials configured for this test stand." in response.text
    assert "env-secret-user" not in response.text
    assert "env-secret-password" not in response.text


@pytest.mark.anyio
async def test_login_form_does_not_render_environment_secret(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGIN_FORM_SECRET", "environment-secret-value")
    config_path = tmp_path / "scenarios.toml"
    config_path.write_text(
        """
[auth]
password_env = "LOGIN_FORM_SECRET"

[presets.protected]
protected = true
""",
        encoding="utf-8",
    )
    configure_auth(load_preset_document(config_path).resolved_auth)

    response = await client.get("/login")

    assert response.status_code == 200
    assert "environment-secret-value" not in response.text


@pytest.mark.anyio
async def test_login_form_uses_the_catalog_visual_system(client: AsyncClient) -> None:
    response = await client.get("/login?next_url=/catalog%3Fprotected%3Dtrue")

    assert response.status_code == 200
    assert 'href="/static/catalog.css"' in response.text
    assert 'class="hero login-hero"' in response.text
    assert 'class="workspace login-workspace"' in response.text
    assert 'class="login-form"' in response.text
    assert 'id="username" name="username" data-testid="username"' in response.text
    assert 'id="password" name="password" data-testid="password" type="password"' in response.text
    assert 'name="next_url" value="/catalog?protected=true"' in response.text


@pytest.mark.anyio
async def test_custom_login_test_ids_are_rendered_without_changing_form_names(
    client: AsyncClient,
) -> None:
    configure_selectors(
        SelectorConfig(
            username="account-name",
            password="account-secret",
            login_button="submit-login",
        )
    )

    response = await client.get("/login")

    assert 'name="username" data-testid="account-name"' in response.text
    assert 'name="password" data-testid="account-secret"' in response.text
    assert 'type="submit" data-testid="submit-login"' in response.text


@pytest.mark.anyio
async def test_custom_catalog_test_ids_are_in_runtime_config_and_dom_renderer(
    client: AsyncClient,
) -> None:
    configure_selectors(
        SelectorConfig(
            catalog="product-list",
            item="product-card",
            item_name="product-title",
            item_price="product-cost",
            next_page="page-forward",
        )
    )

    response = await client.get("/catalog")
    script = await client.get("/static/catalog.js")

    assert 'data-testid="product-list"' in response.text
    assert '"item": "product-card"' in response.text
    assert '"item_name": "product-title"' in response.text
    assert '"item_price": "product-cost"' in response.text
    assert '"next_page": "page-forward"' in response.text
    assert "config.selectors.item" in script.text
    assert "config.selectors.next_page" in script.text
    assert "textContent = item.name" in script.text
    assert "innerHTML" not in script.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("missing", '<button type="submit">Sign in</button>'),
        ("changed", 'data-testid="login-submit-changed"'),
        ("multiple", 'data-testid="login-submit"'),
        ("delayed", "setTimeout"),
        ("hidden", "hidden>Sign in</button>"),
        ("disabled", "disabled>Sign in</button>"),
    ],
)
async def test_login_button_selector_failure_modes(
    client: AsyncClient,
    mode: str,
    expected: str,
) -> None:
    response = await client.get(
        "/login?next_url=%2Fcatalog%3Fscenario%3Dselector-failure"
        f"&selector_failure_target=login_button&selector_failure_mode={mode}"
    )

    assert response.status_code == 200
    assert expected in response.text
    if mode == "multiple":
        assert response.text.count('data-testid="login-submit"') == 2


@pytest.mark.anyio
async def test_selector_failure_is_page_and_target_scoped_and_deterministic(
    client: AsyncClient,
) -> None:
    failure = SelectorFailureConfig(target="item", mode="hidden", page=2)
    configure_scenario_defaults(
        ScenarioDefaults(scenario="selector-failure", total_pages=3, selector_failure=failure)
    )

    first = await client.get("/catalog?run_id=scoped-failure")
    second = await client.get("/catalog?run_id=scoped-failure")
    other_scenario = await client.get("/catalog?scenario=success&run_id=scoped-failure")
    out_of_range = await client.get(
        "/catalog?scenario=selector-failure&total_pages=1&run_id=scoped-failure"
    )

    assert first.text == second.text
    assert (
        '"selectorFailure": {"target": "item", "mode": "hidden", "page": 2, "delayMs": 500}'
        in first.text
    )
    assert '"selectorFailure": null' in other_scenario.text
    assert '"selectorFailure": null' in out_of_range.text


@pytest.mark.anyio
async def test_selector_failure_query_overrides_target_and_page(client: AsyncClient) -> None:
    response = await client.get(
        "/catalog?scenario=selector-failure&total_pages=3&selector_failure_target=next_page"
        "&selector_failure_mode=disabled&selector_failure_page=2"
    )

    assert response.status_code == 200
    assert (
        '"selectorFailure": {"target": "next_page", "mode": "disabled", "page": 2, "delayMs": 500}'
        in response.text
    )


@pytest.mark.anyio
async def test_selector_failure_rejects_incomplete_and_invalid_query_config(
    client: AsyncClient,
) -> None:
    incomplete = await client.get("/catalog?scenario=selector-failure&selector_failure_target=item")
    invalid_mode = await client.get(
        "/catalog?scenario=selector-failure&selector_failure_target=item"
        "&selector_failure_mode=unknown"
    )
    invalid_login_page = await client.get(
        "/catalog?scenario=selector-failure&selector_failure_target=login_button"
        "&selector_failure_mode=missing&selector_failure_page=2"
    )

    assert incomplete.status_code == 422
    assert invalid_mode.status_code == 422
    assert invalid_login_page.status_code == 422


@pytest.mark.anyio
async def test_selector_failure_api_scenario_keeps_deterministic_catalog_payload(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/catalog?scenario=selector-failure&run_id=selector-api&"
        "selector_failure_target=item&selector_failure_mode=multiple&selector_failure_page=2&page=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "selector-failure"
    assert payload["page"] == 2
    assert len(payload["items"]) == 5


@pytest.mark.anyio
async def test_protected_selector_failure_preserves_login_button_configuration(
    client: AsyncClient,
) -> None:
    configure_scenario_defaults(
        ScenarioDefaults(
            scenario="selector-failure",
            protected=True,
            selector_failure=SelectorFailureConfig(target="login_button", mode="hidden"),
        )
    )

    catalog_response = await client.get("/catalog")
    login_response = await client.get(catalog_response.headers["location"])

    assert catalog_response.status_code == 303
    assert login_response.status_code == 200
    assert 'data-testid="login-submit" hidden' in login_response.text


@pytest.mark.anyio
async def test_dom_change_scenario_keeps_its_existing_structure(client: AsyncClient) -> None:
    response = await client.get("/catalog?scenario=dom-change")
    script = await client.get("/static/catalog.js")

    assert '"selectorFailure": null' in response.text
    assert "'article' : 'div'" in script.text
    assert "'result-tile-v2' : 'product-card'" in script.text
    assert "content.className = 'content'" in script.text
    assert "failure?.target === target && failure.page === page" in script.text
    assert "setFailureState(outer, 'item', data.page" in script.text
    assert "setFailureState(next, 'next_page', data.page" in script.text
    assert "mode === 'missing'" in script.text
    assert "mode === 'changed'" in script.text
    assert "itemMode === 'multiple'" in script.text
    assert "itemMode === 'delayed'" in script.text
    assert "mode === 'hidden'" in script.text
    assert "mode === 'disabled'" in script.text
    assert "nextMode === 'multiple'" in script.text
    assert "nextMode === 'delayed'" in script.text


@pytest.mark.anyio
async def test_login_returns_to_configured_ten_page_catalog(client: AsyncClient) -> None:
    protected = await client.get(
        "/catalog?protected=true&scenario=transient&run_id=login-flow&total_pages=10"
        "&fail_for=2&failure_delay_ms=1500",
        follow_redirects=False,
    )
    next_url = parse_qs(urlsplit(protected.headers["location"]).query)["next_url"][0]

    login = await client.post(
        "/login",
        data={"username": "demo", "password": "automation", "next_url": next_url},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == next_url

    catalog = await client.get(login.headers["location"])
    assert catalog.status_code == 200
    assert '"totalPages": 10' in catalog.text
    assert '"failureDelayMs": 1500' in catalog.text


@pytest.mark.anyio
async def test_resume_scenario_fails_only_on_configured_page(client: AsyncClient) -> None:
    base = "/api/catalog?scenario=resume&run_id=resume-case&fail_page=3"
    assert (await client.get(f"{base}&page=2")).status_code == 200
    assert (await client.get(f"{base}&page=3")).status_code == 500
    assert (await client.get(f"{base}&page=4")).status_code == 200


@pytest.mark.anyio
async def test_catalog_can_expose_ten_pages(client: AsyncClient) -> None:
    response = await client.get(
        "/api/catalog?scenario=success&run_id=ten-pages&page=10&total_pages=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 10
    assert payload["total_pages"] == 10
    assert payload["items"][0]["id"] == "item-046"
    assert payload["items"][-1]["id"] == "item-050"


@pytest.mark.anyio
async def test_transient_failure_can_be_delayed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(app_module.asyncio, "sleep", record_delay)
    url = (
        "/api/catalog?scenario=transient&run_id=delayed-retry&page=1"
        "&fail_for=1&failure_delay_ms=1250&total_pages=10"
    )

    assert (await client.get(url)).status_code == 503
    recovered = await client.get(url)
    assert recovered.status_code == 200
    assert recovered.json()["total_pages"] == 10
    assert delays == [1.25]


@pytest.mark.anyio
async def test_active_preset_supplies_request_defaults(client: AsyncClient) -> None:
    configure_scenario_defaults(
        ScenarioDefaults(
            scenario="transient",
            protected=True,
            total_pages=10,
            fail_for=1,
            failure_delay_ms=0,
        )
    )

    protected = await client.get("/catalog?run_id=preset-login", follow_redirects=False)
    assert protected.status_code == 303
    next_url = parse_qs(urlsplit(protected.headers["location"]).query)["next_url"][0]
    assert "scenario=transient" in next_url
    assert "total_pages=10" in next_url

    first = await client.get("/api/catalog?run_id=preset-api&page=10")
    assert first.status_code == 503
    recovered = await client.get("/api/catalog?run_id=preset-api&page=10")
    assert recovered.status_code == 200
    assert recovered.json()["total_pages"] == 10


@pytest.mark.anyio
async def test_query_parameters_override_only_selected_preset_fields(
    client: AsyncClient,
) -> None:
    configure_scenario_defaults(ScenarioDefaults(scenario="transient", total_pages=10, fail_for=3))

    response = await client.get(
        "/api/catalog?run_id=preset-override&page=2&scenario=success&total_pages=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "success"
    assert payload["total_pages"] == 2
    assert payload["items"][-1]["id"] == "item-010"
