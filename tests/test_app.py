from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

import resilient_automation_test_stand.main as app_module
from resilient_automation_test_stand.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        await test_client.post("/admin/reset")
        yield test_client


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.anyio
async def test_catalog_page_loads_dynamic_shell(client: AsyncClient) -> None:
    response = await client.get("/catalog?scenario=success&run_id=test")
    assert response.status_code == 200
    assert "data-testid=\"catalog\"" in response.text
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
