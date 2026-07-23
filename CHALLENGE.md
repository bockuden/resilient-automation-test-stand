# Resilience Challenge

Use this exercise to prove a browser or HTTP automation worker recovers from
repeatable failures. It is deliberately small: the result should be a runnable
test, a short report, or both—not a benchmark claim.

Start the stand first:

```bash
docker compose up --build --detach --wait
```

Use a fresh `run_id` for every attempt. The stand remembers retry attempts per
`run_id`; `POST /admin/reset` is available only for controlled test setup.

## Level 1 — complete a happy-path catalog

**Entry URL**

```text
http://localhost:8080/catalog?scenario=success&run_id=challenge-l1&total_pages=3
```

**Goal**: collect every item across the three pages.

- Success means exactly 15 unique item IDs, five from each page.
- Record the number of pages and item IDs your worker observed.
- Do not hard-code catalog names, prices, or a final item count into the
  consumer.
- Do not skip browser pagination by assuming the next page URL shape; use the
  documented API or the `data-testid="next-page"` control.

## Level 2 — respect transient failures

**Entry URL**

```text
http://localhost:8080/catalog?scenario=transient&run_id=challenge-l2&total_pages=3&fail_for=2
```

**Goal**: complete the same 15-item collection while honoring the retry
contract.

- Each page initially returns two `503` responses with `Retry-After: 1`.
- Success means 15 unique item IDs and no more than three requests per page.
- Record the attempt count, wait durations, and final result for every page.
- Do not retry immediately, retry indefinitely, or treat `503` as a successful
  empty page.
- Do not call `/admin/reset` between retries; that would erase the behavior
  under test.

## Level 3 — survive browser-specific changes

Run both protected scenarios below with one preserved login session.

**DOM change**

```text
http://localhost:8080/catalog?scenario=dom-change&protected=true&run_id=challenge-l3-dom&total_pages=3
```

**Duplicates**

```text
http://localhost:8080/catalog?scenario=duplicates&protected=true&run_id=challenge-l3-duplicates&total_pages=3
```

**Goal**: log in once per scenario, preserve the session, and collect a
deduplicated result.

- Use the fixed demo credentials from the README: `demo` / `automation`.
- For DOM change, use stable `data-testid` locators; CSS class names and HTML
  element names intentionally change.
- For duplicates, report 13 unique IDs from 15 rendered items: page 2 repeats
  the final item from page 1, and page 3 repeats the final item from page 2.
- Record the final URL after login and the duplicate IDs your consumer removed.
- Do not bypass the login by calling the API directly, scrape by CSS class, or
  drop duplicates by position rather than stable item ID.

## Bonus — recovery evidence

Choose one or both exercises:

| Scenario | URL parameters | Evidence to keep |
| --- | --- | --- |
| Resume | `scenario=resume&run_id=challenge-bonus-resume&total_pages=4&fail_page=3` | checkpoint after page 2, failure details, and a recorded resume decision |
| Cancellation | `scenario=slow&run_id=challenge-bonus-cancel&delay_ms=5000` | cancellation signal, elapsed time, and clean shutdown or retry decision |

The worker should distinguish a permanent failure from a transient retryable
failure and leave enough evidence for another engineer to reproduce it.

## Reference material

- [Python Playwright retry recipe](README.md#python-playwright-retry-a-transient-browser-scenario)
- [C# resilient browser automation consumer](https://github.com/bockuden/resilient-browser-automation)
- [Public compatibility policy](docs/compatibility.md)

Share only reproducible output: the scenario URL without credentials, the
consumer version or commit, and the collected metrics. The challenge is not a
substitute for the API contract or for an end-to-end production test.
