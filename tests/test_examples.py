import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from types import ModuleType, TracebackType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from resilient_automation_test_stand.examples import (
    api_retry_dedup,
    http_support,
    playwright_resilience,
    resume_checkpoint,
)
from resilient_automation_test_stand.examples.api_retry_dedup import run_demo
from resilient_automation_test_stand.examples.http_support import JsonResponse
from resilient_automation_test_stand.examples.playwright_resilience import (
    catalog_url,
    exercise_browser,
)
from resilient_automation_test_stand.examples.resume_checkpoint import (
    ResumeFailure,
    collect_with_checkpoint,
)
from resilient_automation_test_stand.main import (
    app,
    configure_scenario_defaults,
    request_attempts,
)
from resilient_automation_test_stand.presets import ScenarioDefaults


@pytest.fixture
def client() -> Iterator[TestClient]:
    request_attempts.clear()
    configure_scenario_defaults(ScenarioDefaults())
    with TestClient(app) as test_client:
        yield test_client
    request_attempts.clear()
    configure_scenario_defaults(ScenarioDefaults())


def request_adapter(client: TestClient):
    def request_json(url: str) -> JsonResponse:
        parsed = urlsplit(url)
        response = client.get(f"{parsed.path}?{parsed.query}")
        return JsonResponse(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.json(),
        )

    return request_json


def test_api_example_proves_retry_pagination_and_dedup(client: TestClient) -> None:
    sleeps: list[float] = []

    evidence = run_demo(
        "http://testserver",
        run_id="tested-api-example",
        total_pages=3,
        fail_for=2,
        max_attempts=3,
        request_json=request_adapter(client),
        sleep=sleeps.append,
    )

    assert evidence["transient"] == {
        "scenario": "transient",
        "run_id": "tested-api-example-retry",
        "pages": 3,
        "requests": 9,
        "wait_seconds": [1.0] * 6,
        "raw_items": 15,
        "unique_items": 15,
        "duplicate_ids": [],
    }
    assert evidence["duplicates"]["raw_items"] == 15
    assert evidence["duplicates"]["unique_items"] == 13
    assert evidence["duplicates"]["duplicate_ids"] == ["item-005", "item-010"]
    assert sleeps == [1.0] * 6


def test_api_example_fails_when_retry_budget_is_exhausted(client: TestClient) -> None:
    with pytest.raises(RuntimeError, match="Retry budget exhausted after 2 attempts"):
        run_demo(
            "http://testserver",
            run_id="tested-api-budget",
            total_pages=3,
            fail_for=2,
            max_attempts=2,
            request_json=request_adapter(client),
            sleep=lambda _: None,
        )


def test_http_support_reads_a_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[Any] = []

    class FakeResponse:
        status = 200

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "application/json")]

        def read(self) -> bytes:
            return b'{"status": "ok"}'

    class FakeConnection:
        def __init__(self, host: str, *, port: int | None, timeout: float) -> None:
            events.append(("connect", host, port, timeout))

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            events.append(("request", method, target, headers))

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(http_support, "HTTPConnection", FakeConnection)

    response = http_support.get_json("http://example.test:8080/api/catalog?page=2", timeout=3)

    assert response == JsonResponse(
        status=200,
        headers={"Content-Type": "application/json"},
        body={"status": "ok"},
    )
    assert events == [
        ("connect", "example.test", 8080, 3),
        (
            "request",
            "GET",
            "/api/catalog?page=2",
            {"User-Agent": "resilient-automation-example/1"},
        ),
        "close",
    ]


def test_http_support_rejects_invalid_urls_and_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="absolute HTTP URL"):
        http_support.get_json("not-an-http-url")

    class ListResponse:
        status = 200

        def getheaders(self) -> list[tuple[str, str]]:
            return []

        def read(self) -> bytes:
            return b"[]"

    class ListConnection:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def request(self, *_: Any, **__: Any) -> None:
            pass

        def getresponse(self) -> ListResponse:
            return ListResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(http_support, "HTTPConnection", ListConnection)
    with pytest.raises(RuntimeError, match="Expected a JSON object"):
        http_support.get_json("http://example.test/list")


def test_api_example_main_prints_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        api_retry_dedup,
        "run_demo",
        lambda *args, **kwargs: {
            "base_url": args[0],
            "run_id": kwargs["run_id"],
            "verified": True,
        },
    )

    assert (
        api_retry_dedup.main(
            [
                "--base-url",
                "http://stand.test",
                "--run-id",
                "main-api-example",
            ]
        )
        == 0
    )
    assert '"base_url": "http://stand.test"' in capsys.readouterr().out


def test_resume_example_preserves_and_reuses_checkpoint(
    client: TestClient,
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "resume.json"

    with pytest.raises(ResumeFailure) as failure:
        collect_with_checkpoint(
            "http://testserver",
            scenario="resume",
            checkpoint_path=checkpoint,
            run_id="tested-resume-example",
            total_pages=4,
            fail_page=3,
            request_json=request_adapter(client),
        )

    assert failure.value.page == 3
    failed_state = checkpoint.read_text(encoding="utf-8")
    assert '"next_page": 3' in failed_state
    assert '"item-010"' in failed_state
    assert '"item-011"' not in failed_state

    requested_pages: list[int] = []
    base_request = request_adapter(client)

    def recording_request(url: str) -> JsonResponse:
        requested_pages.append(int(parse_qs(urlsplit(url).query)["page"][0]))
        return base_request(url)

    evidence = collect_with_checkpoint(
        "http://testserver",
        scenario="success",
        checkpoint_path=checkpoint,
        run_id=None,
        total_pages=4,
        fail_page=3,
        request_json=recording_request,
    )

    assert evidence["resumed_from_page"] == 3
    assert evidence["requested_pages"] == [3, 4]
    assert requested_pages == [3, 4]
    assert evidence["unique_items"] == 20
    assert evidence["completed"] is True


def test_resume_example_main_reports_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "main-resume.json"
    monkeypatch.setattr(
        resume_checkpoint,
        "collect_with_checkpoint",
        lambda *args, **kwargs: {"completed": True, "checkpoint": str(checkpoint)},
    )

    assert resume_checkpoint.main(["--checkpoint", str(checkpoint)]) == 0
    assert '"completed": true' in capsys.readouterr().out

    def fail(*_: Any, **__: Any) -> dict[str, Any]:
        raise ResumeFailure(page=3, status=500, checkpoint=checkpoint)

    monkeypatch.setattr(resume_checkpoint, "collect_with_checkpoint", fail)
    assert resume_checkpoint.main(["--checkpoint", str(checkpoint)]) == 1
    assert "Page 3 failed with HTTP 500" in capsys.readouterr().err


class FakeTimeoutError(Exception):
    pass


class FakeNavigation(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeLocator:
    def __init__(self, page: "FakePage", kind: str) -> None:
        self.page = page
        self.kind = kind

    @property
    def first(self) -> "FakeLocator":
        return self

    def fill(self, value: str) -> None:
        self.page.filled[self.kind] = value

    def click(self) -> None:
        self.page.url = self.page.catalog_url
        self.page.api_attempt = 1

    def wait_for(self, **_: Any) -> None:
        if self.kind == "catalog-item" and self.page.api_attempt <= self.page.fail_for:
            raise FakeTimeoutError

    def inner_text(self) -> str:
        return "Catalog error: HTTP 503; retry-after=1"

    def count(self) -> int:
        return 5


class FakePage:
    def __init__(self, *, fail_for: int) -> None:
        self.fail_for = fail_for
        self.api_attempt = 0
        self.reloads = 0
        self.url = "about:blank"
        self.catalog_url = ""
        self.filled: dict[str, str] = {}

    def goto(self, url: str) -> None:
        self.catalog_url = url
        self.url = "http://testserver/login"

    def get_by_label(self, label: str) -> FakeLocator:
        return FakeLocator(self, label)

    def get_by_role(self, role: str, *, name: str) -> FakeLocator:
        assert (role, name) == ("button", "Sign in")
        return FakeLocator(self, "sign-in")

    def get_by_test_id(self, test_id: str) -> FakeLocator:
        return FakeLocator(self, test_id)

    def expect_navigation(self) -> FakeNavigation:
        return FakeNavigation()

    def reload(self) -> None:
        self.reloads += 1
        self.api_attempt += 1


def test_playwright_example_logs_in_and_honors_retry_after() -> None:
    page = FakePage(fail_for=2)
    sleeps: list[float] = []
    url = catalog_url("http://testserver", run_id="tested-browser-example", fail_for=2)

    evidence = exercise_browser(
        page,
        url=url,
        timeout_error=FakeTimeoutError,
        max_attempts=3,
        sleep=sleeps.append,
    )

    assert page.filled == {"Username": "demo", "Password": "automation"}
    assert page.reloads == 2
    assert sleeps == [1.0, 1.0]
    assert evidence == {
        "attempts": 3,
        "wait_seconds": [1.0, 1.0],
        "item_count": 5,
        "final_url": url,
    }


def test_playwright_example_fails_when_retry_budget_is_exhausted() -> None:
    page = FakePage(fail_for=2)

    with pytest.raises(RuntimeError, match="within 2 attempts"):
        exercise_browser(
            page,
            url=catalog_url("http://testserver", run_id="budget-example", fail_for=2),
            timeout_error=FakeTimeoutError,
            max_attempts=2,
            sleep=lambda _: None,
        )

    assert page.reloads == 1


def test_playwright_example_main_runs_optional_consumer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []

    class FakeBrowser:
        def new_page(self) -> object:
            return object()

        def close(self) -> None:
            closed.append(True)

    class FakeChromium:
        def launch(self, *, headless: bool) -> FakeBrowser:
            assert headless is True
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContext(AbstractContextManager[FakePlaywright]):
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr(
        playwright_resilience,
        "exercise_browser",
        lambda *args, **kwargs: {
            "attempts": 3,
            "item_count": 5,
            "url": kwargs["url"],
        },
    )
    playwright_package = ModuleType("playwright")
    sync_api = ModuleType("playwright.sync_api")
    sync_api.TimeoutError = FakeTimeoutError
    sync_api.sync_playwright = FakePlaywrightContext
    playwright_package.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright_package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    assert (
        playwright_resilience.main(
            [
                "--base-url",
                "http://stand.test",
                "--run-id",
                "main-browser-example",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"attempts": 3' in output
    assert "main-browser-example" in output
    assert closed == [True]


def test_readme_has_one_canonical_scenario_matrix_and_links_examples() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert readme.count("## What each case proves") == 1
    assert "\n## Scenarios\n" not in readme
    module = "python -m resilient_automation_test_stand.examples"
    assert f"{module}.api_retry_dedup" in readme
    assert f"{module}.playwright_resilience" in readme
    assert f"{module}.resume_checkpoint" in readme
