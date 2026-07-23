import asyncio
import json
from collections import defaultdict
from html import escape
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Cookie, FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from resilient_automation_test_stand.presets import Scenario, ScenarioDefaults

app = FastAPI(
    title="Resilient Browser Automation Test Stand",
    version="0.3.0",
    docs_url="/api-docs",
)
app.state.scenario_defaults = ScenarioDefaults()

request_attempts: dict[tuple[str, str, int], int] = defaultdict(int)


def configure_scenario_defaults(defaults: ScenarioDefaults) -> None:
    app.state.scenario_defaults = defaults


def _resolved_defaults(**overrides: object | None) -> ScenarioDefaults:
    current: ScenarioDefaults = app.state.scenario_defaults
    values = current.model_dump()
    values.update({name: value for name, value in overrides.items() if value is not None})
    return ScenarioDefaults.model_validate(values)


class CatalogItem(BaseModel):
    id: str = Field(description="Stable deterministic item identifier.")
    name: str = Field(description="Deterministic display name for the item.")
    price: float = Field(description="Deterministic item price.")


class CatalogPage(BaseModel):
    page: int = Field(description="One-based page that produced this response.")
    total_pages: int = Field(description="Total pages exposed by the scenario.")
    items: list[CatalogItem] = Field(description="Items for the requested page.")
    scenario: Scenario = Field(description="Resolved scenario name.")
    attempt: int = Field(description="One-based request attempt for this run, scenario, and page.")


@app.get(
    "/health",
    operation_id="get_health",
    summary="Check service health",
    description="Returns a deterministic readiness response for container and service checks.",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/admin/reset",
    operation_id="reset_attempt_counters",
    summary="Reset deterministic attempt counters",
    description="Test-only operation that clears all in-memory request-attempt counters.",
)
async def reset() -> dict[str, int]:
    cleared = len(request_attempts)
    request_attempts.clear()
    return {"clearedCounters": cleared}


@app.get(
    "/login",
    response_class=HTMLResponse,
    operation_id="get_demo_login_form",
    summary="Render the demo login form",
    description="Renders the fixed-credential form used only by protected catalog scenarios.",
)
async def login_form(next_url: str = "/catalog") -> str:
    safe_next = escape(next_url, quote=True)
    return f"""
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Demo login</title></head>
  <body>
    <main>
      <h1>Demo login</h1>
      <form method="post" action="/login">
        <input type="hidden" name="next_url" value="{safe_next}">
        <label>Username <input name="username" autocomplete="username"></label>
        <label>Password <input name="password" type="password" autocomplete="current-password"></label>
        <button type="submit">Sign in</button>
      </form>
    </main>
  </body>
</html>
"""


@app.post(
    "/login",
    status_code=303,
    operation_id="submit_demo_login",
    summary="Authenticate to a protected demo catalog",
    description="Accepts the fixed demo credentials and redirects to a local catalog URL.",
    responses={401: {"description": "The supplied demo credentials are invalid."}},
)
async def login(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_url: Annotated[str, Form()] = "/catalog",
) -> RedirectResponse:
    if username != "demo" or password != "automation":
        raise HTTPException(status_code=401, detail="Invalid demo credentials")

    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/catalog"
    response = RedirectResponse(safe_next, status_code=303)
    response.set_cookie("demo_session", "authenticated", httponly=True, samesite="lax")
    return response


@app.get(
    "/catalog",
    response_class=HTMLResponse,
    operation_id="get_catalog_shell",
    summary="Render the browser catalog shell",
    description=(
        "Renders a JavaScript catalog UI. Protected scenarios redirect to the demo login form. "
        "Use stable data-testid locators when automating this page."
    ),
    responses={303: {"description": "Protected catalog redirects to the demo login form."}},
)
async def catalog(
    scenario: Scenario | None = Query(default=None, description="Scenario to execute; inherits the active preset when omitted."),
    run_id: str = Query(default="manual", description="Opaque key that isolates deterministic attempt counters between test runs."),
    fail_for: int | None = Query(default=None, ge=0, le=10, description="Initial transient failures per page."),
    delay_ms: int | None = Query(default=None, ge=0, le=30_000, description="Response delay for the slow scenario, in milliseconds."),
    failure_delay_ms: int | None = Query(default=None, ge=0, le=30_000, description="Delay before each transient 503 response, in milliseconds."),
    fail_page: int | None = Query(default=None, ge=1, le=20, description="Permanently failing page in the resume scenario."),
    total_pages: int | None = Query(default=None, ge=1, le=20, description="Number of pages exposed by the catalog."),
    protected: bool | None = Query(default=None, description="Require the fixed demo login before serving the catalog shell."),
    demo_session: Annotated[str | None, Cookie()] = None,
) -> HTMLResponse:
    defaults = _resolved_defaults(
        scenario=scenario,
        protected=protected,
        total_pages=total_pages,
        fail_for=fail_for,
        failure_delay_ms=failure_delay_ms,
        delay_ms=delay_ms,
        fail_page=fail_page,
    )

    if defaults.protected and demo_session != "authenticated":
        target_query = urlencode(
            {
                "scenario": defaults.scenario,
                "run_id": run_id,
                "fail_for": defaults.fail_for,
                "delay_ms": defaults.delay_ms,
                "failure_delay_ms": defaults.failure_delay_ms,
                "fail_page": defaults.fail_page,
                "total_pages": defaults.total_pages,
                "protected": "true",
            }
        )
        login_query = urlencode({"next_url": f"/catalog?{target_query}"})
        return RedirectResponse(f"/login?{login_query}", status_code=303)

    config = {
        "scenario": defaults.scenario,
        "runId": run_id,
        "failFor": defaults.fail_for,
        "delayMs": defaults.delay_ms,
        "failureDelayMs": defaults.failure_delay_ms,
        "failPage": defaults.fail_page,
        "totalPages": defaults.total_pages,
    }
    return HTMLResponse(_catalog_html(config))


@app.get(
    "/api/catalog",
    response_model=CatalogPage,
    operation_id="get_catalog_page",
    summary="Fetch one deterministic catalog page",
    description=(
        "Returns deterministic catalog data for retry, pagination, duplicate, delay, "
        "and checkpoint-recovery tests."
    ),
    responses={
        500: {"description": "Permanent or checkpoint-resume scenario failure."},
        503: {"description": "Transient scenario failure; includes the Retry-After header."},
    },
)
async def catalog_api(
    page: int = Query(default=1, ge=1, le=20, description="One-based catalog page to fetch."),
    scenario: Scenario | None = Query(default=None, description="Scenario to execute; inherits the active preset when omitted."),
    run_id: str = Query(default="manual", description="Opaque key that isolates deterministic attempt counters between test runs."),
    fail_for: int | None = Query(default=None, ge=0, le=10, description="Initial transient failures per page."),
    delay_ms: int | None = Query(default=None, ge=0, le=30_000, description="Response delay for the slow scenario, in milliseconds."),
    failure_delay_ms: int | None = Query(default=None, ge=0, le=30_000, description="Delay before each transient 503 response, in milliseconds."),
    fail_page: int | None = Query(default=None, ge=1, le=20, description="Permanently failing page in the resume scenario."),
    total_pages: int | None = Query(default=None, ge=1, le=20, description="Number of pages exposed by the catalog."),
) -> CatalogPage:
    defaults = _resolved_defaults(
        scenario=scenario,
        total_pages=total_pages,
        fail_for=fail_for,
        failure_delay_ms=failure_delay_ms,
        delay_ms=delay_ms,
        fail_page=fail_page,
    )
    key = (run_id, defaults.scenario, page)
    request_attempts[key] += 1
    attempt = request_attempts[key]

    if defaults.scenario == "transient" and attempt <= defaults.fail_for:
        if defaults.failure_delay_ms:
            await asyncio.sleep(defaults.failure_delay_ms / 1000)
        raise HTTPException(
            status_code=503,
            detail={"code": "TRANSIENT_CATALOG_FAILURE", "attempt": attempt},
            headers={"Retry-After": "1"},
        )

    if defaults.scenario == "permanent":
        raise HTTPException(
            status_code=500,
            detail={"code": "PERMANENT_CATALOG_FAILURE", "attempt": attempt},
        )

    if defaults.scenario == "resume" and page == defaults.fail_page:
        raise HTTPException(
            status_code=500,
            detail={"code": "CHECKPOINT_RESUME_FAILURE", "page": page, "attempt": attempt},
        )

    if defaults.scenario == "slow":
        await asyncio.sleep(defaults.delay_ms / 1000)

    return CatalogPage(
        page=page,
        total_pages=defaults.total_pages,
        items=_items_for_page(page, defaults.scenario, defaults.total_pages),
        scenario=defaults.scenario,
        attempt=attempt,
    )


def _items_for_page(page: int, scenario: Scenario, total_pages: int) -> list[CatalogItem]:
    if page > total_pages:
        return []

    first = (page - 1) * 5 + 1
    identifiers = list(range(first, first + 5))
    if scenario == "duplicates" and page > 1:
        identifiers[0] = first - 1

    return [
        CatalogItem(
            id=f"item-{identifier:03d}",
            name=f"Catalog item {identifier}",
            price=identifier + 0.99,
        )
        for identifier in identifiers
    ]


def _catalog_html(config: dict[str, object]) -> str:
    serialized = json.dumps(config).replace("<", "\\u003c")
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Deterministic demo catalog</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
      #catalog {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }}
      [data-testid="catalog-item"] {{ border: 1px solid #bbb; border-radius: .5rem; padding: 1rem; }}
      #status {{ min-height: 1.5rem; }}
      nav {{ display: flex; gap: .5rem; margin-top: 1rem; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Deterministic demo catalog</h1>
      <p id="scenario">Scenario: <strong>{escape(str(config['scenario']))}</strong></p>
      <p id="status" role="status">Loading page 1...</p>
      <section id="catalog" data-testid="catalog"></section>
      <nav aria-label="Catalog pagination"></nav>
    </main>
    <script>
      const config = {serialized};
      const catalog = document.querySelector('#catalog');
      const status = document.querySelector('#status');
      const nav = document.querySelector('nav');

      async function loadPage(page) {{
        status.textContent = `Loading page ${{page}}...`;
        catalog.replaceChildren();
        nav.replaceChildren();
        const query = new URLSearchParams({{
          page,
          scenario: config.scenario,
          run_id: config.runId,
          fail_for: config.failFor,
          delay_ms: config.delayMs,
          failure_delay_ms: config.failureDelayMs,
          fail_page: config.failPage,
          total_pages: config.totalPages,
        }});

        try {{
          const response = await fetch(`/api/catalog?${{query}}`);
          if (!response.ok) {{
            const retryAfter = response.headers.get('Retry-After');
            throw new Error(`HTTP ${{response.status}}${{retryAfter ? `; retry-after=${{retryAfter}}` : ''}}`);
          }}
          const data = await response.json();
          const fragment = document.createDocumentFragment();

          for (const item of data.items) {{
            const outer = document.createElement(config.scenario === 'dom-change' ? 'article' : 'div');
            outer.className = config.scenario === 'dom-change' ? 'result-tile-v2' : 'product-card';
            outer.dataset.testid = 'catalog-item';
            outer.dataset.itemId = item.id;
            outer.innerHTML = config.scenario === 'dom-change'
              ? `<div class="content"><span data-testid="item-name">${{item.name}}</span><strong data-testid="item-price">${{item.price.toFixed(2)}}</strong></div>`
              : `<h2 data-testid="item-name">${{item.name}}</h2><span data-testid="item-price">${{item.price.toFixed(2)}}</span>`;
            fragment.appendChild(outer);
          }}

          catalog.appendChild(fragment);
          status.textContent = `Page ${{data.page}} loaded on attempt ${{data.attempt}}`;

          if (data.page < data.total_pages) {{
            const next = document.createElement('button');
            next.type = 'button';
            next.dataset.testid = 'next-page';
            next.textContent = 'Next page';
            next.addEventListener('click', () => loadPage(data.page + 1));
            nav.appendChild(next);
          }}
        }} catch (error) {{
          status.textContent = `Catalog error: ${{error.message}}`;
          status.dataset.testid = 'catalog-error';
        }}
      }}

      loadPage(1);
    </script>
  </body>
</html>
"""
