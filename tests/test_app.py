import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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
    response = await client.get("/catalog?protected=true", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


@pytest.mark.anyio
async def test_login_sets_session_cookie(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "demo", "password": "automation", "next_url": "/catalog?protected=true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.cookies["demo_session"] == "authenticated"
