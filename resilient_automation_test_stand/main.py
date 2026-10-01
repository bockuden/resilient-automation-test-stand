import asyncio
import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import Cookie, FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from resilient_automation_test_stand.presets import (
    ResolvedAuth,
    Scenario,
    ScenarioDefaults,
    SelectorConfig,
    SelectorFailureConfig,
    SelectorFailureMode,
    SelectorFailureTarget,
)

app = FastAPI(
    title="Resilient Browser Automation Test Stand",
    version="1.1.5",
    docs_url="/api-docs",
)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).with_name("static")),
    name="static",
)
app.state.scenario_defaults = ScenarioDefaults()
app.state.auth = ResolvedAuth()
app.state.selectors = SelectorConfig()

request_attempts: dict[tuple[str, str, int], int] = defaultdict(int)


def configure_scenario_defaults(defaults: ScenarioDefaults) -> None:
    app.state.scenario_defaults = defaults


def configure_auth(auth: ResolvedAuth) -> None:
    app.state.auth = auth


def configure_selectors(selectors: SelectorConfig) -> None:
    app.state.selectors = selectors


def _resolved_defaults(query: "CatalogQuery") -> ScenarioDefaults:
    current: ScenarioDefaults = app.state.scenario_defaults
    values = current.model_dump()
    values.update(
        query.model_dump(
            exclude_none=True,
            exclude={
                "page",
                "run_id",
                "selector_failure_target",
                "selector_failure_mode",
                "selector_failure_page",
                "selector_failure_delay_ms",
            },
        )
    )
    if query.selector_failure_target is not None:
        values["selector_failure"] = SelectorFailureConfig(
            target=query.selector_failure_target,
            mode=query.selector_failure_mode,
            page=query.selector_failure_page or 1,
            delay_ms=query.selector_failure_delay_ms or 500,
        )
    return ScenarioDefaults.model_validate(values)


def _runtime_selector_failure(defaults: ScenarioDefaults) -> dict[str, object] | None:
    failure = defaults.selector_failure
    if (
        defaults.scenario != "selector-failure"
        or failure is None
        or failure.page > defaults.total_pages
    ):
        return None
    return {
        "target": failure.target,
        "mode": failure.mode,
        "page": failure.page,
        "delayMs": failure.delay_ms,
    }


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


class CatalogQuery(BaseModel):
    scenario: Scenario | None = Field(
        default=None,
        description="Scenario to execute; inherits the active preset when omitted.",
    )
    run_id: str = Field(
        default="manual",
        description="Opaque key that isolates deterministic attempt counters between test runs.",
    )
    fail_for: int | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Initial transient failures per page.",
    )
    delay_ms: int | None = Field(
        default=None,
        ge=0,
        le=30_000,
        description="Response delay for the slow scenario, in milliseconds.",
    )
    failure_delay_ms: int | None = Field(
        default=None,
        ge=0,
        le=30_000,
        description="Delay before each transient 503 response, in milliseconds.",
    )
    fail_page: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Permanently failing page in the resume scenario.",
    )
    total_pages: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Number of pages exposed by the catalog.",
    )
    rate_limit_for: int | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Initial HTTP 429 responses per page in the rate-limit scenario.",
    )
    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
        le=300,
        description="Retry-After value for rate-limit responses, in seconds.",
    )
    selector_failure_target: SelectorFailureTarget | None = Field(
        default=None,
        description="Browser locator target for the selector-failure scenario.",
    )
    selector_failure_mode: SelectorFailureMode | None = Field(
        default=None,
        description="Deterministic failure mode for the configured browser locator.",
    )
    selector_failure_page: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Catalog page where the locator failure is activated.",
    )
    selector_failure_delay_ms: int | None = Field(
        default=None,
        ge=1,
        le=5000,
        description="Bounded delay before a configured locator appears.",
    )

    @model_validator(mode="after")
    def validate_selector_failure_query(self) -> "CatalogQuery":
        if (self.selector_failure_target is None) != (self.selector_failure_mode is None):
            raise ValueError(
                "selector_failure_target and selector_failure_mode must be set together"
            )
        if self.selector_failure_target is None and (
            self.selector_failure_page is not None or self.selector_failure_delay_ms is not None
        ):
            raise ValueError(
                "selector_failure_page and selector_failure_delay_ms require a target and mode"
            )
        if self.selector_failure_target == "login_button" and self.selector_failure_page not in (
            None,
            1,
        ):
            raise ValueError("login_button selector failures apply only to page 1")
        return self


class CatalogShellQuery(CatalogQuery):
    protected: bool | None = Field(
        default=None,
        description="Require login with configured credentials before serving the catalog shell.",
    )


class CatalogApiQuery(CatalogQuery):
    page: int = Field(
        default=1,
        ge=1,
        le=20,
        description="One-based catalog page to fetch.",
    )


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
    description="Renders the configured-credential form used by protected catalog scenarios.",
)
async def login_form(
    next_url: str = "/catalog",
    selector_failure_target: SelectorFailureTarget | None = None,
    selector_failure_mode: SelectorFailureMode | None = None,
    selector_failure_page: Annotated[int | None, Query(ge=1, le=20)] = None,
    selector_failure_delay_ms: Annotated[int | None, Query(ge=1, le=5000)] = None,
) -> str:
    safe_next = escape(next_url, quote=True)
    selectors: SelectorConfig = app.state.selectors
    requested_scenario = parse_qs(urlsplit(next_url).query).get("scenario")
    failure = None
    if (
        requested_scenario == ["selector-failure"]
        and selector_failure_target == "login_button"
        and selector_failure_mode is not None
        and selector_failure_page in (None, 1)
    ):
        failure = SelectorFailureConfig(
            target="login_button",
            mode=selector_failure_mode,
            page=1,
            delay_ms=selector_failure_delay_ms or 500,
        )

    login_test_id = selectors.login_button
    login_test_id_attr = f' data-testid="{escape(login_test_id, quote=True)}"'
    login_button_id = ""
    login_button_hidden = ""
    login_button_disabled = ""
    login_button_duplicate = ""
    login_button_script = ""
    if failure is not None:
        if failure.mode == "missing":
            login_test_id_attr = ""
        elif failure.mode == "changed":
            login_test_id_attr = f' data-testid="{escape(login_test_id + "-changed", quote=True)}"'
        elif failure.mode == "multiple":
            login_button_duplicate = (
                f'<button type="submit" data-testid="{escape(login_test_id, quote=True)}">'
                "Sign in (duplicate)</button>"
            )
        elif failure.mode == "delayed":
            login_button_id = ' id="login-submit-control"'
            login_button_hidden = " hidden"
            login_button_script = (
                "<script>setTimeout(() => { const button = "
                "document.getElementById('login-submit-control'); "
                f"button.dataset.testid = {json.dumps(login_test_id)}; "
                "button.hidden = false; }, "
                f"{failure.delay_ms});</script>"
            )
        elif failure.mode == "hidden":
            login_button_hidden = " hidden"
        elif failure.mode == "disabled":
            login_button_disabled = " disabled"
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Demo login | Resilient Automation Test Stand</title>
    <link rel="stylesheet" href="/static/catalog.css">
  </head>
  <body>
    <main>
      <header class="hero login-hero">
        <span class="eyebrow">RESILIENCE TEST TARGET</span>
        <h1>Demo login</h1>
        <p class="lede">Sign in to continue the protected catalog scenario.</p>
      </header>
      <section class="workspace login-workspace" aria-labelledby="login-title">
        <div class="login-intro">
          <h2 id="login-title">Continue your test run</h2>
          <p>Use the credentials configured for this test stand.</p>
        </div>
        <form class="login-form" method="post" action="/login">
          <input type="hidden" name="next_url" value="{safe_next}">
          <label for="username">Username</label>
          <input id="username" name="username" data-testid="{escape(selectors.username, quote=True)}" autocomplete="username" required>
          <label for="password">Password</label>
          <input id="password" name="password" data-testid="{escape(selectors.password, quote=True)}" type="password" autocomplete="current-password" required>
          <button{login_button_id} type="submit"{login_test_id_attr}{login_button_hidden}{login_button_disabled}>Sign in</button>
          {login_button_duplicate}
        </form>
        {login_button_script}
      </section>
    </main>
  </body>
</html>
"""


@app.post(
    "/login",
    status_code=303,
    operation_id="submit_demo_login",
    summary="Authenticate to a protected demo catalog",
    description="Accepts the configured credentials and redirects to a local catalog URL.",
    responses={401: {"description": "The supplied credentials are invalid."}},
)
async def login(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_url: Annotated[str, Form()] = "/catalog",
) -> RedirectResponse:
    auth: ResolvedAuth = app.state.auth
    if username != auth.username or password != auth.password:
        raise HTTPException(status_code=401, detail="Invalid demo credentials")

    safe_next = (
        next_url if next_url.startswith("/") and not next_url.startswith("//") else "/catalog"
    )
    response = RedirectResponse(safe_next, status_code=303)
    response.set_cookie("demo_session", "authenticated", httponly=True, samesite="lax")
    return response


@app.get(
    "/catalog",
    response_class=HTMLResponse,
    operation_id="get_catalog_shell",
    summary="Render the browser catalog shell",
    description=(
        "Renders a JavaScript catalog UI. Protected scenarios redirect to the configured login form. "
        "Use stable data-testid locators when automating this page."
    ),
    responses={303: {"description": "Protected catalog redirects to the configured login form."}},
)
async def catalog(
    query: Annotated[CatalogShellQuery, Query()],
    demo_session: Annotated[str | None, Cookie()] = None,
) -> HTMLResponse:
    defaults = _resolved_defaults(query)

    if defaults.protected and demo_session != "authenticated":
        failure_query = (
            {
                f"selector_failure_{name}": value
                for name, value in defaults.selector_failure.model_dump().items()
            }
            if defaults.selector_failure is not None
            else {}
        )
        target_query = urlencode(
            {
                "scenario": defaults.scenario,
                "run_id": query.run_id,
                "fail_for": defaults.fail_for,
                "delay_ms": defaults.delay_ms,
                "failure_delay_ms": defaults.failure_delay_ms,
                "fail_page": defaults.fail_page,
                "total_pages": defaults.total_pages,
                "rate_limit_for": defaults.rate_limit_for,
                "retry_after_seconds": defaults.retry_after_seconds,
                "protected": "true",
                **failure_query,
            }
        )
        login_query = urlencode({"next_url": f"/catalog?{target_query}", **failure_query})
        return RedirectResponse(f"/login?{login_query}", status_code=303)

    config = {
        "scenario": defaults.scenario,
        "runId": query.run_id,
        "failFor": defaults.fail_for,
        "delayMs": defaults.delay_ms,
        "failureDelayMs": defaults.failure_delay_ms,
        "failPage": defaults.fail_page,
        "totalPages": defaults.total_pages,
        "rateLimitFor": defaults.rate_limit_for,
        "retryAfterSeconds": defaults.retry_after_seconds,
        "selectors": app.state.selectors.model_dump(),
        "selectorFailure": _runtime_selector_failure(defaults),
    }
    return HTMLResponse(_catalog_html(config))


@app.get(
    "/api/catalog",
    response_model=CatalogPage,
    operation_id="get_catalog_page",
    summary="Fetch one deterministic catalog page",
    description=(
        "Returns deterministic catalog data for retry, pagination, duplicate, rate-limit, delay, "
        "and checkpoint-recovery tests."
    ),
    responses={
        500: {"description": "Permanent or checkpoint-resume scenario failure."},
        503: {"description": "Transient scenario failure; includes the Retry-After header."},
        429: {"description": "Rate-limit scenario response; includes the Retry-After header."},
    },
)
async def catalog_api(
    query: Annotated[CatalogApiQuery, Query()],
) -> CatalogPage:
    defaults = _resolved_defaults(query)
    key = (query.run_id, defaults.scenario, query.page)
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

    if defaults.scenario == "rate-limit" and attempt <= defaults.rate_limit_for:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "attempt": attempt},
            headers={"Retry-After": str(defaults.retry_after_seconds)},
        )

    if defaults.scenario == "permanent":
        raise HTTPException(
            status_code=500,
            detail={"code": "PERMANENT_CATALOG_FAILURE", "attempt": attempt},
        )

    if defaults.scenario == "resume" and query.page == defaults.fail_page:
        raise HTTPException(
            status_code=500,
            detail={"code": "CHECKPOINT_RESUME_FAILURE", "page": query.page, "attempt": attempt},
        )

    if defaults.scenario == "slow":
        await asyncio.sleep(defaults.delay_ms / 1000)

    return CatalogPage(
        page=query.page,
        total_pages=defaults.total_pages,
        items=_items_for_page(query.page, defaults.scenario, defaults.total_pages),
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
    <link rel="stylesheet" href="/static/catalog.css">
  </head>
  <body>
    <main>
      <header class="hero">
        <span class="eyebrow">RESILIENCE TEST TARGET</span>
        <h1>Deterministic demo catalog</h1>
        <p class="lede">A predictable browser surface for proving recovery, pagination, and durable automation behavior.</p>
      </header>
      <p id="scenario" class="scenario-pill">Scenario: <strong>{escape(str(config["scenario"]))}</strong></p>
      <section class="workspace" aria-label="Catalog result">
        <p id="status" role="status" data-state="loading">Loading page 1...</p>
        <section id="catalog" class="catalog-items" data-testid="{escape(str(config["selectors"]["catalog"]), quote=True)}"></section>
        <nav aria-label="Catalog pagination"></nav>
      </section>
    </main>
    <script id="catalog-config" type="application/json">{serialized}</script>
    <script src="/static/catalog.js" defer></script>
  </body>
</html>
"""
