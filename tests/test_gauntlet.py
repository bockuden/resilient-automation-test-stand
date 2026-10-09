import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

import resilient_automation_test_stand.main as app_module
from resilient_automation_test_stand import gauntlet
from resilient_automation_test_stand.gauntlet import (
    LEVELS,
    GauntletEvidence,
    evidence_template,
    validate_evidence,
)
from resilient_automation_test_stand.main import (
    app,
    configure_auth,
    configure_scenario_defaults,
    configure_selectors,
)
from resilient_automation_test_stand.presets import ResolvedAuth, ScenarioDefaults, SelectorConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    configure_scenario_defaults(ScenarioDefaults())
    configure_auth(ResolvedAuth())
    configure_selectors(SelectorConfig())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        await test_client.post("/admin/reset")
        yield test_client


def passing_evidence(level: int) -> GauntletEvidence:
    spec = LEVELS[level]
    pages = []
    for page_number in range(1, spec.total_pages + 1):
        statuses = gauntlet._expected_statuses(spec, page_number)
        retry_count = sum(status in {429, 503} for status in statuses)
        pages.append(
            {
                "page": page_number,
                "statuses": statuses,
                "retry_wait_seconds": [1.0] * retry_count,
                "item_ids": gauntlet._expected_item_ids(
                    page_number,
                    duplicate=page_number in spec.duplicate_pages,
                ),
                "elapsed_ms": (spec.minimum_delay_ms if page_number == spec.delayed_page else 0),
            }
        )
    return GauntletEvidence.model_validate(
        {
            "schema_version": 1,
            "level": level,
            "run_id": f"gauntlet-l{level}",
            "pages": pages,
            "logins": spec.expected_logins or 0,
            "session_expirations": spec.expected_session_expirations or 0,
            "checkpoint_after_page": spec.expected_checkpoint_page,
            "resumed_at_page": spec.expected_resume_page,
            "reprocessed_pages": [],
            "selector_changes_handled": list(spec.expected_selector_changes),
        }
    )


@pytest.mark.parametrize("level", range(1, 11))
def test_every_gauntlet_level_accepts_exact_deterministic_evidence(level: int) -> None:
    evidence = passing_evidence(level)

    report = validate_evidence(evidence)

    assert report.passed is True
    assert report.errors == []
    assert report.metrics["pages_processed"] == LEVELS[level].total_pages
    assert report.metrics["rendered_items"] == LEVELS[level].total_pages * 5
    assert report.metrics["duplicates_removed"] == len(LEVELS[level].duplicate_pages)


@pytest.mark.parametrize(
    ("level", "mutation", "expected_error"),
    [
        (1, "missing_page", "missing pages"),
        (2, "missing_wait", "retry waits"),
        (3, "wrong_logins", "logins must be 1"),
        (4, "missing_selector", "selector_changes_handled"),
        (5, "wrong_items", "item_ids do not match"),
        (6, "wrong_checkpoint", "checkpoint_after_page must be 2"),
        (6, "reprocessed_page", "reprocessed_pages must be empty"),
        (7, "wrong_expiry_count", "session_expirations must be 1"),
        (8, "wrong_statuses", "statuses must be [429, 429, 200]"),
        (9, "short_delay", "elapsed_ms must be at least 250"),
        (10, "wrong_resume", "resumed_at_page must be 5"),
    ],
)
def test_gauntlet_reports_objective_failures(
    level: int,
    mutation: str,
    expected_error: str,
) -> None:
    values = passing_evidence(level).model_dump()
    if mutation == "missing_page":
        values["pages"].pop()
    elif mutation == "missing_wait":
        values["pages"][0]["retry_wait_seconds"] = []
    elif mutation == "wrong_logins":
        values["logins"] = 0
    elif mutation == "missing_selector":
        values["selector_changes_handled"] = []
    elif mutation == "wrong_items":
        values["pages"][1]["item_ids"][0] = "item-999"
    elif mutation == "wrong_checkpoint":
        values["checkpoint_after_page"] = 1
    elif mutation == "reprocessed_page":
        values["reprocessed_pages"] = [1]
    elif mutation == "wrong_expiry_count":
        values["session_expirations"] = 0
    elif mutation == "wrong_statuses":
        values["pages"][0]["statuses"] = [429, 200]
    elif mutation == "short_delay":
        values["pages"][5]["elapsed_ms"] = 249
    elif mutation == "wrong_resume":
        values["resumed_at_page"] = 4

    report = validate_evidence(GauntletEvidence.model_validate(values))

    assert report.passed is False
    assert any(expected_error in error for error in report.errors)


def test_gauntlet_rejects_duplicate_page_evidence() -> None:
    values = passing_evidence(1).model_dump()
    values["pages"].append(values["pages"][0])

    report = validate_evidence(GauntletEvidence.model_validate(values))

    assert report.passed is False
    assert "duplicate page evidence: 1" in report.errors


def test_gauntlet_evidence_schema_is_strict() -> None:
    values = passing_evidence(1).model_dump()
    values["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GauntletEvidence.model_validate(values)


def test_composite_level_urls_carry_expected_event_sequences() -> None:
    level_nine_query = parse_qs(urlsplit(LEVELS[9].entry_urls[0]).query)
    level_ten_query = parse_qs(urlsplit(LEVELS[10].entry_urls[0]).query)

    assert [event["type"] for event in json.loads(level_nine_query["events_json"][0])] == [
        "http_error",
        "duplicate_items",
        "delay",
    ]
    assert [event["type"] for event in json.loads(level_ten_query["events_json"][0])] == [
        "http_error",
        "duplicate_items",
        "expire_session",
        "selector_change",
        "delay",
    ]


def test_evidence_template_is_portable_and_intentionally_incomplete() -> None:
    template = evidence_template(10)

    evidence = GauntletEvidence.model_validate(template)
    report = validate_evidence(evidence)

    assert template["schema_version"] == 1
    assert len(template["pages"]) == 10
    assert report.passed is False


def test_gauntlet_cli_lists_and_describes_levels(capsys: pytest.CaptureFixture[str]) -> None:
    assert gauntlet.main(["list"]) == 0
    levels = json.loads(capsys.readouterr().out)
    assert [level["level"] for level in levels] == list(range(1, 11))

    assert gauntlet.main(["describe", "10"]) == 0
    description = json.loads(capsys.readouterr().out)
    assert description["slug"] == "composite-recovery"
    assert description["entry_urls"] == list(LEVELS[10].entry_urls)


def test_gauntlet_cli_validates_pass_and_fail_reports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(passing_evidence(2).model_dump_json(indent=2), encoding="utf-8")

    assert gauntlet.main(["validate", str(path)]) == 0
    passing_report = json.loads(capsys.readouterr().out)
    assert passing_report["passed"] is True

    values = passing_evidence(2).model_dump()
    values["pages"][0]["retry_wait_seconds"] = []
    path.write_text(json.dumps(values), encoding="utf-8")

    assert gauntlet.main(["validate", str(path)]) == 1
    failing_report = json.loads(capsys.readouterr().out)
    assert failing_report["passed"] is False
    assert failing_report["errors"]


def test_gauntlet_cli_returns_machine_readable_schema_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version": 1, "level": 99}', encoding="utf-8")

    assert gauntlet.main(["validate", str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
    assert result["error"] == "invalid evidence"
    assert isinstance(result["details"], list)


@pytest.mark.anyio
@pytest.mark.parametrize("level", range(1, 11))
async def test_level_urls_drive_server_sequences_that_pass_validation(
    level: int,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = LEVELS[level]
    primary = urlsplit(spec.entry_urls[0])
    primary_params = {name: values[0] for name, values in parse_qs(primary.query).items()}
    recovery_params = None
    if len(spec.entry_urls) > 1:
        recovery = urlsplit(spec.entry_urls[1])
        recovery_params = {name: values[0] for name, values in parse_qs(recovery.query).items()}
        recovery_params.pop("resume_page", None)

    sleep_calls: list[int] = []

    async def record_sleep(seconds: float) -> None:
        sleep_calls.append(round(seconds * 1000))

    monkeypatch.setattr(app_module.asyncio, "sleep", record_sleep)

    logins = 0
    if spec.expected_logins:
        login = await client.post(
            "/login",
            data={
                "username": "demo",
                "password": "automation",
                "next_url": f"{primary.path}?{primary.query}",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        logins += 1

    selector_changes: list[str] = []
    if spec.expected_selector_changes:
        shell = await client.get(primary.path, params=primary_params)
        assert shell.status_code == 200
        for selector_change in spec.expected_selector_changes:
            target, page = selector_change.split("@", maxsplit=1)
            assert target in shell.text
            assert page in shell.text
            selector_changes.append(selector_change)

    page_evidence = []
    session_expirations = 0
    for page_number in range(1, spec.total_pages + 1):
        statuses: list[int] = []
        retry_waits: list[float] = []
        sleep_start = len(sleep_calls)
        active_params = primary_params
        response = None
        while response is None or response.status_code != 200:
            response = await client.get(
                "/api/catalog",
                params={**active_params, "page": page_number},
            )
            statuses.append(response.status_code)
            if response.status_code in {429, 503}:
                assert response.headers["retry-after"] == "1"
                retry_waits.append(1.0)
            elif response.status_code == 500 and recovery_params is not None:
                active_params = recovery_params
            elif response.status_code == 401:
                assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
                session_expirations += 1
                relogin = await client.post(
                    "/login",
                    data={
                        "username": "demo",
                        "password": "automation",
                        "next_url": f"{primary.path}?{primary.query}",
                    },
                    follow_redirects=False,
                )
                assert relogin.status_code == 303
                logins += 1
            else:
                assert response.status_code == 200

        page_evidence.append(
            {
                "page": page_number,
                "statuses": statuses,
                "retry_wait_seconds": retry_waits,
                "item_ids": [item["id"] for item in response.json()["items"]],
                "elapsed_ms": sum(sleep_calls[sleep_start:]),
            }
        )

    evidence = GauntletEvidence.model_validate(
        {
            "schema_version": 1,
            "level": level,
            "run_id": primary_params["run_id"],
            "pages": page_evidence,
            "logins": logins,
            "session_expirations": session_expirations,
            "checkpoint_after_page": spec.expected_checkpoint_page,
            "resumed_at_page": spec.expected_resume_page,
            "reprocessed_pages": [],
            "selector_changes_handled": selector_changes,
        }
    )

    report = validate_evidence(evidence)

    assert report.passed is True, report.errors
