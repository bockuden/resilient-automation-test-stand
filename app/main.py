import asyncio
import json
from collections import defaultdict
from html import escape
from typing import Annotated, Literal

from fastapi import Cookie, FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel


Scenario = Literal[
    "success",
    "transient",
    "permanent",
    "slow",
    "dom-change",
    "duplicates",
]

app = FastAPI(
    title="Resilient Browser Automation Test Stand",
    version="0.1.0",
    docs_url="/api-docs",
)

request_attempts: dict[tuple[str, str, int], int] = defaultdict(int)


class CatalogItem(BaseModel):
    id: str
    name: str
    price: float


class CatalogPage(BaseModel):
    page: int
    total_pages: int
    items: list[CatalogItem]
    scenario: Scenario
    attempt: int


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/reset")
async def reset() -> dict[str, int]:
    cleared = len(request_attempts)
    request_attempts.clear()
    return {"clearedCounters": cleared}


@app.get("/login", response_class=HTMLResponse)
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


@app.post("/login")
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


@app.get("/catalog", response_class=HTMLResponse)
async def catalog(
    scenario: Scenario = "success",
    run_id: str = "manual",
    fail_for: int = Query(default=2, ge=0, le=10),
    delay_ms: int = Query(default=1500, ge=0, le=30_000),
    protected: bool = False,
    demo_session: Annotated[str | None, Cookie()] = None,
) -> HTMLResponse:
    if protected and demo_session != "authenticated":
        query = f"scenario={scenario}&run_id={run_id}&fail_for={fail_for}&delay_ms={delay_ms}&protected=true"
        return RedirectResponse(f"/login?next_url=/catalog?{query}", status_code=303)

    config = {
        "scenario": scenario,
        "runId": run_id,
        "failFor": fail_for,
        "delayMs": delay_ms,
    }
    return HTMLResponse(_catalog_html(config))


@app.get("/api/catalog", response_model=CatalogPage)
async def catalog_api(
    page: int = Query(default=1, ge=1, le=20),
    scenario: Scenario = "success",
    run_id: str = "manual",
    fail_for: int = Query(default=2, ge=0, le=10),
    delay_ms: int = Query(default=1500, ge=0, le=30_000),
) -> CatalogPage:
    key = (run_id, scenario, page)
    request_attempts[key] += 1
    attempt = request_attempts[key]

    if scenario == "transient" and attempt <= fail_for:
        raise HTTPException(
            status_code=503,
            detail={"code": "TRANSIENT_CATALOG_FAILURE", "attempt": attempt},
            headers={"Retry-After": "1"},
        )

    if scenario == "permanent":
        raise HTTPException(
            status_code=500,
            detail={"code": "PERMANENT_CATALOG_FAILURE", "attempt": attempt},
        )

    if scenario == "slow":
        await asyncio.sleep(delay_ms / 1000)

    total_pages = 4
    return CatalogPage(
        page=page,
        total_pages=total_pages,
        items=_items_for_page(page, scenario, total_pages),
        scenario=scenario,
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
