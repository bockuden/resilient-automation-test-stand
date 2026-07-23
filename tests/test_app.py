from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

import resilient_automation_test_stand.main as app_module
from resilient_automation_test_stand.main import app, configure_scenario_defaults
from resilient_automation_test_stand.presets import ScenarioDefaults


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    configure_scenario_defaults(ScenarioDefaults())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        await test_client.post("/admin/reset")
        try:
            yield test_client
        finally:
            configure_scenario_defaults(ScenarioDefaults())


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.anyio
async def test_catalog_page_loads_dynamic_shell(client: AsyncClient) -> None:
    response = await client.get("/catalog?scenario=success&run_id=test")
    assert response.status_code == 200
    assert 'data-testid="catalog"' in response.text
    assert "loadPage(1)" in response.text


@pytest.mark.anyio
async def test_transient_scenario_fails_twice_then_recovers(client: AsyncClient) -> None:
    url = "/api/catalog?scenario=transient&run_id=retry-case&page=1&fail_for=2"
    assert (await client.get(url)).status_code == 503
    assert (await client.get(url)).status_code == 503
    recovered = await client.get(url)
    assert recovered.status_code == 200
    assert recovered.json()["attempt"] == 3


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
