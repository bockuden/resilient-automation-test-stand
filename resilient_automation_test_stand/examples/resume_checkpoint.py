"""Persist a page checkpoint, fail visibly, and resume on the next run."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from resilient_automation_test_stand.examples.http_support import JsonResponse, get_json

RequestJson = Callable[[str], JsonResponse]


class ResumeFailure(RuntimeError):
    def __init__(self, *, page: int, status: int, checkpoint: Path) -> None:
        super().__init__(
            f"Page {page} failed with HTTP {status}; checkpoint preserved at {checkpoint}"
        )
        self.page = page
        self.status = status
        self.checkpoint = checkpoint


def load_checkpoint(path: Path, *, run_id: str | None, total_pages: int) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise RuntimeError("Checkpoint must contain a JSON object")
        if run_id is not None and state.get("run_id") != run_id:
            raise RuntimeError("The supplied run_id does not match the checkpoint")
        if state.get("total_pages") != total_pages:
            raise RuntimeError("The supplied total_pages does not match the checkpoint")
        return state

    return {
        "run_id": run_id or f"resume-example-{uuid.uuid4().hex[:12]}",
        "total_pages": total_pages,
        "next_page": 1,
        "items": {},
        "completed": False,
        "last_failure": None,
    }


def save_checkpoint(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def catalog_url(
    base_url: str,
    *,
    scenario: str,
    run_id: str,
    page: int,
    total_pages: int,
    fail_page: int,
) -> str:
    query = urlencode(
        {
            "scenario": scenario,
            "run_id": run_id,
            "page": page,
            "total_pages": total_pages,
            "fail_page": fail_page,
        }
    )
    return f"{base_url.rstrip('/')}/api/catalog?{query}"


def collect_with_checkpoint(
    base_url: str,
    *,
    scenario: str,
    checkpoint_path: Path,
    run_id: str | None,
    total_pages: int,
    fail_page: int,
    request_json: RequestJson = get_json,
) -> dict[str, Any]:
    state = load_checkpoint(checkpoint_path, run_id=run_id, total_pages=total_pages)
    stable_run_id = state["run_id"]
    items = state.get("items")
    if not isinstance(stable_run_id, str) or not isinstance(items, dict):
        raise RuntimeError("Checkpoint has invalid run_id or items fields")

    resumed_from_page = int(state["next_page"])
    requested_pages: list[int] = []
    for page in range(resumed_from_page, total_pages + 1):
        requested_pages.append(page)
        response = request_json(
            catalog_url(
                base_url,
                scenario=scenario,
                run_id=stable_run_id,
                page=page,
                total_pages=total_pages,
                fail_page=fail_page,
            )
        )
        if response.status != 200:
            state["last_failure"] = {
                "page": page,
                "status": response.status,
                "scenario": scenario,
            }
            save_checkpoint(checkpoint_path, state)
            raise ResumeFailure(page=page, status=response.status, checkpoint=checkpoint_path)

        page_items = response.body.get("items")
        if not isinstance(page_items, list):
            raise RuntimeError(f"Page {page} did not contain an items list")
        for item in page_items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise RuntimeError(f"Page {page} contained an item without a stable string ID")
            items[item["id"]] = item

        state["next_page"] = page + 1
        state["last_failure"] = None
        state["completed"] = page == total_pages
        save_checkpoint(checkpoint_path, state)

    return {
        "run_id": stable_run_id,
        "scenario": scenario,
        "resumed_from_page": resumed_from_page,
        "requested_pages": requested_pages,
        "unique_items": len(items),
        "completed": state["completed"],
        "checkpoint": str(checkpoint_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--scenario", choices=("resume", "success"), default="resume")
    parser.add_argument("--checkpoint", type=Path, default=Path(".stand-resume.json"))
    parser.add_argument("--run-id")
    parser.add_argument("--total-pages", type=int, default=4)
    parser.add_argument("--fail-page", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        evidence = collect_with_checkpoint(
            args.base_url,
            scenario=args.scenario,
            checkpoint_path=args.checkpoint,
            run_id=args.run_id,
            total_pages=args.total_pages,
            fail_page=args.fail_page,
        )
    except ResumeFailure as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
