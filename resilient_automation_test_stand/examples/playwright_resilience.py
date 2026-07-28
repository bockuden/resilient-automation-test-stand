"""Log in and prove bounded browser recovery from two transient failures."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

Sleep = Callable[[float], None]


def catalog_url(base_url: str, *, run_id: str, fail_for: int) -> str:
    query = urlencode(
        {
            "scenario": "transient",
            "protected": "true",
            "run_id": run_id,
            "fail_for": fail_for,
        }
    )
    return f"{base_url.rstrip('/')}/catalog?{query}"


def retry_after_from_error(message: str) -> float:
    match = re.search(r"HTTP 503; retry-after=(\d+(?:\.\d+)?)", message)
    if match is None:
        raise RuntimeError(f"Expected a retryable catalog error, got: {message}")
    return float(match.group(1))


def exercise_browser(
    page: Any,
    *,
    url: str,
    timeout_error: type[BaseException],
    max_attempts: int,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    page.goto(url)
    page.get_by_label("Username").fill("demo")
    page.get_by_label("Password").fill("automation")
    with page.expect_navigation():
        page.get_by_role("button", name="Sign in").click()
    if "/catalog?" not in page.url:
        raise RuntimeError(f"Login did not return to the catalog: {page.url}")

    waits: list[float] = []
    for attempt in range(1, max_attempts + 1):
        items = page.get_by_test_id("catalog-item")
        try:
            items.first.wait_for(state="visible", timeout=2_000)
        except timeout_error as error:
            catalog_error = page.get_by_test_id("catalog-error")
            catalog_error.wait_for(state="visible", timeout=2_000)
            retry_after = retry_after_from_error(catalog_error.inner_text())
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Transient scenario did not recover within {max_attempts} attempts"
                ) from error
            waits.append(retry_after)
            sleep(retry_after)
            page.reload()
            continue

        item_count = items.count()
        if item_count != 5:
            raise RuntimeError(f"Expected five catalog items, got {item_count}")
        return {
            "attempts": attempt,
            "wait_seconds": waits,
            "item_count": item_count,
            "final_url": page.url,
        }

    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--run-id", default=f"playwright-example-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--fail-for", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Install the optional browser dependency with: "
            "python -m pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    url = catalog_url(args.base_url, run_id=args.run_id, fail_for=args.fail_for)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        try:
            page = browser.new_page()
            evidence = exercise_browser(
                page,
                url=url,
                timeout_error=PlaywrightTimeoutError,
                max_attempts=args.max_attempts,
            )
        finally:
            browser.close()

    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
