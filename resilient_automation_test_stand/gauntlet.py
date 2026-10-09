"""Language-independent evidence validation for the Automation Gauntlet."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

BASE_URL = "http://localhost:8080"


class PageEvidence(BaseModel):
    """Observed request sequence and raw items for one catalog page."""

    model_config = ConfigDict(extra="forbid", strict=True)

    page: int = Field(ge=1, le=20)
    statuses: list[int] = Field(max_length=20)
    retry_wait_seconds: list[float] = Field(default_factory=list, max_length=20)
    item_ids: list[str] = Field(default_factory=list, max_length=100)
    elapsed_ms: int = Field(default=0, ge=0)

    @field_validator("statuses")
    @classmethod
    def validate_status_codes(cls, values: list[int]) -> list[int]:
        if any(value < 100 or value > 599 for value in values):
            raise ValueError("status codes must be between 100 and 599")
        return values

    @field_validator("retry_wait_seconds")
    @classmethod
    def validate_waits(cls, values: list[float]) -> list[float]:
        if any(value < 0 for value in values):
            raise ValueError("retry waits cannot be negative")
        return values

    @field_validator("item_ids")
    @classmethod
    def validate_item_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("item IDs cannot be empty")
        return values


class GauntletEvidence(BaseModel):
    """Portable JSON evidence emitted by any browser or HTTP consumer."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    level: int = Field(ge=1, le=10)
    run_id: str = Field(min_length=1, max_length=100)
    pages: list[PageEvidence] = Field(min_length=1, max_length=20)
    logins: int = Field(default=0, ge=0, le=10)
    session_expirations: int = Field(default=0, ge=0, le=10)
    checkpoint_after_page: int | None = Field(default=None, ge=1, le=20)
    resumed_at_page: int | None = Field(default=None, ge=1, le=20)
    reprocessed_pages: list[int] = Field(default_factory=list, max_length=20)
    selector_changes_handled: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id cannot be blank")
        return value

    @field_validator("reprocessed_pages")
    @classmethod
    def validate_reprocessed_pages(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 20 for value in values):
            raise ValueError("reprocessed page numbers must be between 1 and 20")
        return values


class ValidationReport(BaseModel):
    """Stable machine-readable result returned by the validator."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    level: int
    passed: bool
    objective: str
    errors: list[str]
    metrics: dict[str, int]


@dataclass(frozen=True)
class LevelSpec:
    level: int
    slug: str
    title: str
    objective: str
    total_pages: int
    entry_urls: tuple[str, ...]
    scenario: str = "success"
    fail_status: int | None = None
    fail_for: int = 0
    duplicate_pages: tuple[int, ...] = ()
    expected_logins: int | None = None
    expected_session_expirations: int | None = None
    expected_resume_page: int | None = None
    expected_checkpoint_page: int | None = None
    expected_selector_changes: tuple[str, ...] = ()
    delayed_page: int | None = None
    minimum_delay_ms: int = 0
    permanent_failure_page: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "slug": self.slug,
            "title": self.title,
            "objective": self.objective,
            "entry_urls": list(self.entry_urls),
        }


def _catalog_url(run_id: str, **parameters: object) -> str:
    query = urlencode({"run_id": run_id, **parameters})
    return f"{BASE_URL}/catalog?{query}"


def _composite_url(run_id: str, total_pages: int, events: list[dict[str, object]]) -> str:
    return _catalog_url(
        run_id,
        scenario="success",
        total_pages=total_pages,
        events_json=json.dumps(events, separators=(",", ":")),
    )


LEVELS: dict[int, LevelSpec] = {
    1: LevelSpec(
        level=1,
        slug="pagination",
        title="Complete pagination",
        objective="Collect the exact 15-item dataset from three successful pages.",
        total_pages=3,
        entry_urls=(_catalog_url("gauntlet-l1", scenario="success", total_pages=3),),
    ),
    2: LevelSpec(
        level=2,
        slug="retries",
        title="Bounded transient retries",
        objective="Recover after two 503 responses per page while respecting Retry-After.",
        total_pages=3,
        entry_urls=(
            _catalog_url(
                "gauntlet-l2",
                scenario="transient",
                total_pages=3,
                fail_for=2,
            ),
        ),
        scenario="transient",
        fail_status=503,
        fail_for=2,
    ),
    3: LevelSpec(
        level=3,
        slug="authentication",
        title="Protected catalog authentication",
        objective="Authenticate once and collect all three protected catalog pages.",
        total_pages=3,
        entry_urls=(
            _catalog_url(
                "gauntlet-l3",
                scenario="success",
                protected="true",
                total_pages=3,
            ),
        ),
        expected_logins=1,
    ),
    4: LevelSpec(
        level=4,
        slug="selector-change",
        title="Selector change recovery",
        objective="Handle the changed next-page locator on page 2 and finish pagination.",
        total_pages=3,
        entry_urls=(
            _catalog_url(
                "gauntlet-l4",
                scenario="selector-failure",
                total_pages=3,
                selector_failure_target="next_page",
                selector_failure_mode="changed",
                selector_failure_page=2,
            ),
        ),
        scenario="selector-failure",
        expected_selector_changes=("next_page@2",),
    ),
    5: LevelSpec(
        level=5,
        slug="deduplication",
        title="Cross-page deduplication",
        objective="Reduce 15 rendered items to the exact 13-item unique dataset.",
        total_pages=3,
        entry_urls=(_catalog_url("gauntlet-l5", scenario="duplicates", total_pages=3),),
        scenario="duplicates",
        duplicate_pages=(2, 3),
    ),
    6: LevelSpec(
        level=6,
        slug="checkpoint-resume",
        title="Checkpoint and resume",
        objective="Checkpoint after page 2 and resume from page 3 without reprocessing.",
        total_pages=4,
        entry_urls=(
            _catalog_url(
                "gauntlet-l6",
                scenario="resume",
                total_pages=4,
                fail_page=3,
            ),
            _catalog_url("gauntlet-l6", scenario="success", total_pages=4, resume_page=3),
        ),
        scenario="resume",
        permanent_failure_page=3,
        expected_resume_page=3,
        expected_checkpoint_page=2,
    ),
    7: LevelSpec(
        level=7,
        slug="session-expiry",
        title="Session expiry recovery",
        objective="Re-authenticate after page 2 and resume at page 3.",
        total_pages=4,
        entry_urls=(
            _catalog_url(
                "gauntlet-l7",
                scenario="success",
                protected="true",
                total_pages=4,
                expire_session_after_page=2,
            ),
        ),
        expected_logins=2,
        expected_session_expirations=1,
        expected_resume_page=3,
    ),
    8: LevelSpec(
        level=8,
        slug="rate-limiting",
        title="Rate-limit recovery",
        objective="Recover after two 429 responses per page while respecting Retry-After.",
        total_pages=3,
        entry_urls=(
            _catalog_url(
                "gauntlet-l8",
                scenario="rate-limit",
                total_pages=3,
                rate_limit_for=2,
                retry_after_seconds=1,
            ),
        ),
        scenario="rate-limit",
        fail_status=429,
        fail_for=2,
    ),
    9: LevelSpec(
        level=9,
        slug="multiple-failures",
        title="Multiple API failures",
        objective="Recover from retries, deduplicate page 4, and tolerate the page 6 delay.",
        total_pages=6,
        entry_urls=(
            _composite_url(
                "gauntlet-l9",
                6,
                [
                    {"page": 2, "type": "http_error", "status": 503, "attempts": 2},
                    {"page": 4, "type": "duplicate_items"},
                    {"page": 6, "type": "delay", "delay_ms": 250},
                ],
            ),
        ),
        fail_status=503,
        fail_for=2,
        duplicate_pages=(4,),
        delayed_page=6,
        minimum_delay_ms=250,
    ),
    10: LevelSpec(
        level=10,
        slug="composite-recovery",
        title="Composite recovery",
        objective="Complete ten pages through all five deterministic failure primitives.",
        total_pages=10,
        entry_urls=(
            _composite_url(
                "gauntlet-l10",
                10,
                [
                    {"page": 2, "type": "http_error", "status": 503, "attempts": 2},
                    {"page": 4, "type": "duplicate_items"},
                    {"page": 5, "type": "expire_session"},
                    {
                        "page": 7,
                        "type": "selector_change",
                        "target": "next_page",
                    },
                    {"page": 9, "type": "delay", "delay_ms": 3000},
                ],
            ),
        ),
        fail_status=503,
        fail_for=2,
        duplicate_pages=(4,),
        expected_logins=2,
        expected_session_expirations=1,
        expected_resume_page=5,
        expected_selector_changes=("next_page@7",),
        delayed_page=9,
        minimum_delay_ms=3000,
    ),
}


def _expected_item_ids(page: int, duplicate: bool = False) -> list[str]:
    start = (page - 1) * 5 + 1
    identifiers = list(range(start, start + 5))
    if duplicate:
        identifiers[0] = start - 1
    return [f"item-{identifier:03d}" for identifier in identifiers]


def _expected_statuses(spec: LevelSpec, page: int) -> list[int]:
    if spec.permanent_failure_page == page:
        return [500, 200]
    if spec.expected_session_expirations and spec.expected_resume_page == page:
        return [401, 200]
    if spec.fail_status is not None and (spec.level in {2, 8} or page == 2):
        return [spec.fail_status] * spec.fail_for + [200]
    return [200]


def _metrics(evidence: GauntletEvidence) -> dict[str, int]:
    item_ids = [item_id for page in evidence.pages for item_id in page.item_ids]
    return {
        "pages_processed": len(evidence.pages),
        "rendered_items": len(item_ids),
        "unique_items": len(set(item_ids)),
        "duplicates_removed": len(item_ids) - len(set(item_ids)),
        "retryable_failures": sum(
            status in {429, 503} for page in evidence.pages for status in page.statuses
        ),
    }


def validate_evidence(evidence: GauntletEvidence) -> ValidationReport:
    """Validate evidence against the deterministic objective for its level."""

    spec = LEVELS[evidence.level]
    errors: list[str] = []
    pages: dict[int, PageEvidence] = {}
    duplicate_page_numbers: set[int] = set()
    for page in evidence.pages:
        if page.page in pages:
            duplicate_page_numbers.add(page.page)
        pages[page.page] = page
    if duplicate_page_numbers:
        values = ", ".join(str(page) for page in sorted(duplicate_page_numbers))
        errors.append(f"duplicate page evidence: {values}")

    expected_pages = set(range(1, spec.total_pages + 1))
    actual_pages = set(pages)
    if actual_pages != expected_pages:
        missing = sorted(expected_pages - actual_pages)
        unexpected = sorted(actual_pages - expected_pages)
        if missing:
            errors.append(f"missing pages: {missing}")
        if unexpected:
            errors.append(f"unexpected pages: {unexpected}")

    for page_number in sorted(expected_pages & actual_pages):
        page = pages[page_number]
        expected_statuses = _expected_statuses(spec, page_number)
        if page.statuses != expected_statuses:
            errors.append(
                f"page {page_number} statuses must be {expected_statuses}, got {page.statuses}"
            )
        expected_items = _expected_item_ids(
            page_number,
            duplicate=page_number in spec.duplicate_pages,
        )
        if page.item_ids != expected_items:
            errors.append(f"page {page_number} item_ids do not match the deterministic dataset")

        retry_count = sum(status in {429, 503} for status in expected_statuses)
        if retry_count:
            if len(page.retry_wait_seconds) != retry_count:
                errors.append(
                    f"page {page_number} must record {retry_count} retry waits, "
                    f"got {len(page.retry_wait_seconds)}"
                )
            elif any(wait < 1 for wait in page.retry_wait_seconds):
                errors.append(f"page {page_number} retry waits must each be at least 1 second")

    if spec.expected_logins is not None and evidence.logins != spec.expected_logins:
        errors.append(f"logins must be {spec.expected_logins}, got {evidence.logins}")
    if (
        spec.expected_session_expirations is not None
        and evidence.session_expirations != spec.expected_session_expirations
    ):
        errors.append(
            f"session_expirations must be {spec.expected_session_expirations}, "
            f"got {evidence.session_expirations}"
        )
    if (
        spec.expected_resume_page is not None
        and evidence.resumed_at_page != spec.expected_resume_page
    ):
        errors.append(
            f"resumed_at_page must be {spec.expected_resume_page}, got {evidence.resumed_at_page}"
        )
    if (
        spec.expected_checkpoint_page is not None
        and evidence.checkpoint_after_page != spec.expected_checkpoint_page
    ):
        errors.append(
            f"checkpoint_after_page must be {spec.expected_checkpoint_page}, "
            f"got {evidence.checkpoint_after_page}"
        )
    if spec.expected_resume_page is not None and evidence.reprocessed_pages:
        errors.append("reprocessed_pages must be empty after resume")
    expected_selector_changes = list(spec.expected_selector_changes)
    if expected_selector_changes and evidence.selector_changes_handled != expected_selector_changes:
        errors.append(
            "selector_changes_handled must be "
            f"{expected_selector_changes}, got {evidence.selector_changes_handled}"
        )
    if spec.delayed_page is not None and spec.delayed_page in pages:
        elapsed = pages[spec.delayed_page].elapsed_ms
        if elapsed < spec.minimum_delay_ms:
            errors.append(
                f"page {spec.delayed_page} elapsed_ms must be at least "
                f"{spec.minimum_delay_ms}, got {elapsed}"
            )

    metrics = _metrics(evidence)
    expected_rendered = spec.total_pages * 5
    expected_unique = expected_rendered - len(spec.duplicate_pages)
    if metrics["rendered_items"] != expected_rendered:
        errors.append(
            f"rendered item count must be {expected_rendered}, got {metrics['rendered_items']}"
        )
    if metrics["unique_items"] != expected_unique:
        errors.append(f"unique item count must be {expected_unique}, got {metrics['unique_items']}")

    return ValidationReport(
        level=evidence.level,
        passed=not errors,
        objective=spec.objective,
        errors=errors,
        metrics=metrics,
    )


def evidence_template(level: int) -> dict[str, object]:
    """Return a portable starter document for one level."""

    spec = LEVELS[level]
    return {
        "schema_version": 1,
        "level": level,
        "run_id": f"gauntlet-l{level}",
        "pages": [
            {
                "page": page,
                "statuses": [],
                "retry_wait_seconds": [],
                "item_ids": [],
                "elapsed_ms": 0,
            }
            for page in range(1, spec.total_pages + 1)
        ],
        "logins": 0,
        "session_expirations": 0,
        "checkpoint_after_page": None,
        "resumed_at_page": None,
        "reprocessed_pages": [],
        "selector_changes_handled": [],
    }


def _read_evidence(path: str) -> GauntletEvidence:
    content = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return GauntletEvidence.model_validate_json(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="automation-gauntlet",
        description="Inspect Automation Gauntlet levels and validate portable JSON evidence.",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List all deterministic levels as JSON")
    describe = actions.add_parser("describe", help="Describe one level as JSON")
    describe.add_argument("level", type=int, choices=sorted(LEVELS))
    template = actions.add_parser("template", help="Print a starter evidence document")
    template.add_argument("level", type=int, choices=sorted(LEVELS))
    validate = actions.add_parser("validate", help="Validate an evidence JSON file")
    validate.add_argument("evidence", help="Evidence path, or - to read stdin")
    args = parser.parse_args(argv)

    if args.action == "list":
        output: object = [LEVELS[level].as_dict() for level in sorted(LEVELS)]
    elif args.action == "describe":
        output = LEVELS[args.level].as_dict()
    elif args.action == "template":
        output = evidence_template(args.level)
    else:
        try:
            evidence = _read_evidence(args.evidence)
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            if isinstance(error, ValidationError):
                details: object = error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            else:
                details = str(error)
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "passed": False,
                        "error": "invalid evidence",
                        "details": details,
                    },
                    indent=2,
                )
            )
            return 2
        report = validate_evidence(evidence)
        print(report.model_dump_json(indent=2))
        return 0 if report.passed else 1

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
