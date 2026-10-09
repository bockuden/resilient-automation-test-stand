# Automation Gauntlet

Automation Gauntlet is an optional ten-level training mode built from the
ordinary deterministic scenarios. The server keeps its normal HTTP and browser
contract; a separate validator checks portable JSON evidence produced by any
Playwright, Selenium, HTTP, C#, JavaScript, Java, or other consumer.

The result is a reproducible pass/fail report, not a benchmark score.

## Start the stand

From a repository checkout:

```bash
docker compose up --build --detach --wait
```

From an installed package:

```bash
automation-test-stand --port 8080
```

Use a fresh `run_id` for each real attempt. The URLs printed by the level
descriptions use stable example IDs; replace them when repeating a run, or call
`POST /admin/reset` before controlled test setup. Never reset between retries
inside one attempt.

## Inspect levels and validate evidence

The validator is separate from request handling:

```bash
automation-gauntlet list
automation-gauntlet describe 1
automation-gauntlet template 1 > evidence.json
automation-gauntlet validate evidence.json
```

`list`, `describe`, `template`, and `validate` write JSON to standard output.
Validation exits with `0` for pass, `1` for objective failure, and `2` for an
invalid evidence document. Pass `-` instead of a filename to read evidence from
standard input.

The `describe` output contains complete, encoded entry URLs. Level 6 contains a
failure URL followed by its recovery URL. Levels 9 and 10 carry their validated
composite event list in `events_json`.

## Evidence format

Evidence uses JSON schema version `1`. Each `pages` entry records the complete
status sequence for one page and the raw item IDs from its eventual successful
response. Do not deduplicate `item_ids` before recording them; the validator
derives raw, unique, and removed counts.

```json
{
  "schema_version": 1,
  "level": 1,
  "run_id": "my-gauntlet-run",
  "pages": [
    {
      "page": 1,
      "statuses": [200],
      "retry_wait_seconds": [],
      "item_ids": [
        "item-001",
        "item-002",
        "item-003",
        "item-004",
        "item-005"
      ],
      "elapsed_ms": 25
    }
  ],
  "logins": 0,
  "session_expirations": 0,
  "checkpoint_after_page": null,
  "resumed_at_page": null,
  "reprocessed_pages": [],
  "selector_changes_handled": []
}
```

| Field | Meaning |
| --- | --- |
| `statuses` | Every HTTP status observed for that page, in request order. |
| `retry_wait_seconds` | Actual waits before retries caused by `429` or `503`, in the same order. |
| `item_ids` | Raw ordered IDs from the final successful page response. |
| `elapsed_ms` | Elapsed time for the successful response; required for delay levels. |
| `logins` | Successful login submissions during the run. |
| `session_expirations` | Observed `401 SESSION_EXPIRED` responses. |
| `checkpoint_after_page` | Last page durably saved before a checkpoint recovery. |
| `resumed_at_page` | First page requested after checkpoint or session recovery. |
| `reprocessed_pages` | Already completed pages fetched again after recovery. Must be empty. |
| `selector_changes_handled` | Changed targets recorded as `target@page`, for example `next_page@2`. |

Unknown fields, out-of-range values, duplicate page evidence, incomplete page
sets, unexpected statuses, incorrect datasets, and unmet recovery objectives
produce a failing or invalid report with actionable errors.

## Levels and objective criteria

Run `automation-gauntlet describe LEVEL` for the exact URL and objective text.

| Level | Exercise | Deterministic pass criteria |
| --- | --- | --- |
| 1 | Pagination | Pages 1-3 each return `200`; the exact 15-item dataset is collected. |
| 2 | Retries | Every page returns `503`, `503`, `200`; both `Retry-After: 1` waits are respected; 15 items are collected. |
| 3 | Authentication | One successful login is recorded; all three protected pages and 15 items are collected. |
| 4 | Selector change | `next_page@2` is handled; all three pages and 15 items are collected. |
| 5 | Deduplication | 15 raw items produce the exact 13-item unique dataset; two cross-page duplicates are removed. |
| 6 | Checkpoint/resume | Page 3 records `500`, `200`; the checkpoint is after page 2; recovery starts at page 3; no completed page is reprocessed; 20 items are collected. |
| 7 | Session expiry | Page 3 records `401`, `200`; exactly two logins and one expiry occur; recovery resumes at page 3; 20 items are collected. |
| 8 | Rate limiting | Every page returns `429`, `429`, `200`; both `Retry-After: 1` waits are respected; 15 items are collected. |
| 9 | Multiple failures | Page 2 recovers from two `503` responses, page 4 is deduplicated, page 6 observes at least 250 ms delay, and the exact 29-item unique dataset is collected. |
| 10 | Composite recovery | The worker handles two `503` responses on page 2, a duplicate on page 4, session expiry before page 5, `next_page@7`, and a 3000 ms delay on page 9; the exact 49-item unique dataset is collected. |

## Level-specific guidance

### Levels 1-2: pagination and retries

Follow the documented API or the browser's `data-testid="next-page"` control.
Do not infer the next URL, treat a failed response as an empty page, retry
immediately, or retry without a bound.

### Levels 3-4: authentication and selectors

Use the credentials configured for the stand and preserve the session cookie.
Use stable test IDs, roles, or labels. Do not bypass the protected browser flow
by switching to an unprotected API URL, and do not depend on CSS class or HTML
element names.

### Level 5: deduplication

Deduplicate by stable item ID across page boundaries. Page 2 repeats
`item-005`; page 3 repeats `item-010`. Removing items by array position does
not satisfy the objective.

### Level 6: checkpoint/resume

Persist pages 1 and 2 before the deterministic page 3 failure. Use the second
URL from `describe 6` to represent recovery, load the checkpoint, and request
only pages 3 and 4.

### Levels 7-8: session and rate-limit recovery

For session expiry, preserve the full return URL through re-login and continue
at page 3. For rate limiting, distinguish `429` from server errors and honor
each exact `Retry-After` value.

### Levels 9-10: ordered failures

Composite events use the fixed server order documented in the compatibility
policy. A worker must retain earlier results while later failures occur. The
same configuration and `run_id` replay the same request sequence after
`POST /admin/reset`.

## Reference material

- [Python Playwright login and retry example](resilient_automation_test_stand/examples/playwright_resilience.py)
- [HTTP retry, pagination, and deduplication example](resilient_automation_test_stand/examples/api_retry_dedup.py)
- [Checkpoint and resume example](resilient_automation_test_stand/examples/resume_checkpoint.py)
- [C# resilient browser automation consumer](https://github.com/bockuden/resilient-browser-automation)
- [Public compatibility policy](docs/compatibility.md)

Share only reproducible output: scenario URLs without credentials, the
consumer version or commit, the evidence JSON, and the validation report. The
Gauntlet complements the API contract and does not replace production
end-to-end tests.
