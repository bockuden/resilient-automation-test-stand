"""Prove bounded Retry-After handling, pagination, and stable-ID deduplication."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from resilient_automation_test_stand.examples.http_support import JsonResponse, get_json

RequestJson = Callable[[str], JsonResponse]
Sleep = Callable[[float], None]


def catalog_url(
    base_url: str,
    *,
    scenario: str,
    run_id: str,
    page: int,
    total_pages: int,
    fail_for: int = 0,
) -> str:
    query = urlencode(
        {
            "scenario": scenario,
            "run_id": run_id,
            "page": page,
            "total_pages": total_pages,
            "fail_for": fail_for,
        }
    )
    return f"{base_url.rstrip('/')}/api/catalog?{query}"


def fetch_page_with_retry(
    url: str,
    *,
    request_json: RequestJson = get_json,
    sleep: Sleep = time.sleep,
    max_attempts: int,
) -> tuple[dict[str, Any], int, list[float]]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    waits: list[float] = []
    for attempt in range(1, max_attempts + 1):
        response = request_json(url)
        if response.status == 200:
            return response.body, attempt, waits
        if response.status != 503:
            raise RuntimeError(f"Terminal HTTP {response.status} for {url}")
        if attempt == max_attempts:
            break

        raw_retry_after = next(
            (value for name, value in response.headers.items() if name.lower() == "retry-after"),
            None,
        )
        if raw_retry_after is None:
            raise RuntimeError("Retryable 503 response omitted Retry-After")
        retry_after = float(raw_retry_after)
        if retry_after < 0:
            raise RuntimeError("Retry-After must not be negative")
        waits.append(retry_after)
        sleep(retry_after)

    raise RuntimeError(f"Retry budget exhausted after {max_attempts} attempts for {url}")


def collect_catalog(
    base_url: str,
    *,
    scenario: str,
    run_id: str,
    total_pages: int,
    fail_for: int,
    max_attempts: int,
    request_json: RequestJson = get_json,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    waits: list[float] = []
    request_count = 0
    raw_count = 0

    for page in range(1, total_pages + 1):
        url = catalog_url(
            base_url,
            scenario=scenario,
            run_id=run_id,
            page=page,
            total_pages=total_pages,
            fail_for=fail_for,
        )
        payload, attempts, page_waits = fetch_page_with_retry(
            url,
            request_json=request_json,
            sleep=sleep,
            max_attempts=max_attempts,
        )
        request_count += attempts
        waits.extend(page_waits)

        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"Page {page} did not contain an items list")
        raw_count += len(items)
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise RuntimeError(f"Page {page} contained an item without a stable string ID")
            item_id = item["id"]
            if item_id in seen:
                duplicate_ids.append(item_id)
            else:
                seen.add(item_id)

    return {
        "scenario": scenario,
        "run_id": run_id,
        "pages": total_pages,
        "requests": request_count,
        "wait_seconds": waits,
        "raw_items": raw_count,
        "unique_items": len(seen),
        "duplicate_ids": duplicate_ids,
    }


def run_demo(
    base_url: str,
    *,
    run_id: str,
    total_pages: int,
    fail_for: int,
    max_attempts: int,
    request_json: RequestJson = get_json,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    transient = collect_catalog(
        base_url,
        scenario="transient",
        run_id=f"{run_id}-retry",
        total_pages=total_pages,
        fail_for=fail_for,
        max_attempts=max_attempts,
        request_json=request_json,
        sleep=sleep,
    )
    expected_items = total_pages * 5
    if transient["unique_items"] != expected_items:
        raise RuntimeError(
            f"Transient collection produced {transient['unique_items']} unique items; "
            f"expected {expected_items}"
        )

    duplicates = collect_catalog(
        base_url,
        scenario="duplicates",
        run_id=f"{run_id}-dedup",
        total_pages=total_pages,
        fail_for=0,
        max_attempts=1,
        request_json=request_json,
        sleep=sleep,
    )
    expected_unique = expected_items - (total_pages - 1)
    if duplicates["raw_items"] != expected_items or duplicates["unique_items"] != expected_unique:
        raise RuntimeError(
            "Duplicate collection did not match the deterministic pagination contract"
        )

    return {"transient": transient, "duplicates": duplicates}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--run-id", default=f"api-example-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--total-pages", type=int, default=3)
    parser.add_argument("--fail-for", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)

    evidence = run_demo(
        args.base_url,
        run_id=args.run_id,
        total_pages=args.total_pages,
        fail_for=args.fail_for,
        max_attempts=args.max_attempts,
    )
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
