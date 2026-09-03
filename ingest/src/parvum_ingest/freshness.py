"""Bronze freshness gate: has the pipeline gone dark?

The bronze job runs unattended on a file-arrival trigger, and email covers it
only when it *runs and fails*. It cannot catch the job **never firing** — the
D-018 blind spot (file-arrival triggers ignore overwrites, and a stopped
trigger sends nothing). This check closes that gap from the outside: after the
daily feed lands, it asks the lakehouse *"when did bronze last do any work?"*
and fails the workflow (which then emails, via GitHub's built-in Actions
notification) if the answer is too old.

It runs inside the daily GitHub Action, which has open egress and the
Databricks secrets — so it reaches the SQL API directly, unlike the Databricks
job itself. Note the corollary: this catches a dead *Databricks job*, not a
dead *Action* (an Action that never runs can't run its own check — that needs
an external dead man's switch, deferred to Phase 9 observability).

Design choices, both deliberate:
- **Fail on a stale signal, and on no signal at all.** This originally failed
  only on a confident stale verdict — config missing, query error and empty
  table all warned and exited 0, reasoning that monitoring must not take down
  the pipeline it watches. On 2026-09-03 that reasoning cost us: the SQL API
  returned HTTP 400 for ~100 minutes, ``except URLError`` swallowed it
  (``HTTPError`` subclasses ``URLError``), and the daily run went green having
  never checked freshness at all — while the two jobs *without* such a catch
  went red and got noticed within the day. A gate that cannot answer must not
  report green. A failure surviving the retries below now exits non-zero, with
  a message separating "could not run" from "bronze is stale" (D-088).
  Unconfigured secrets stay a warning: that is a setup state, not a gate going
  blind mid-flight. An empty table stays a pass — nothing has run yet.
- **Checks the outcome, not the process.** "When did bronze last ingest?"
  catches a job that succeeded-but-did-nothing, was deleted, or stopped
  triggering — none of which a run-status check would see.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

_REGISTRY = "workspace.parvum.bronze_file_registry"
_DEFAULT_MAX_AGE_DAYS = 4

# Deliberately a copy of the policy in parvum_export.sql_api, not an import:
# ingest may depend on reference and nothing else, and a shared HTTP client is
# not reference data. Both lists must move together — 400 is in them because
# the API demonstrably returns it for transient conditions (D-088).
_RETRY_STATUSES = frozenset({400, 408, 425, 429, 500, 502, 503, 504})
_BACKOFF_SECONDS = (2, 8, 20)


class FreshnessUnavailable(RuntimeError):
    """The gate got no answer, so it cannot vouch for bronze either way."""


def _parse_ts(raw: str) -> datetime:
    """Parse a Databricks SQL timestamp string into an aware UTC datetime.

    Values arrive like ``2026-07-17T15:04:15.123Z`` or ``2026-07-17 15:04:15``;
    normalise both to naive-then-UTC.
    """
    text = raw.replace("Z", "").replace("T", " ").split(".")[0].strip()
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def evaluate(
    last_run: str | None, last_statement_date: str | None, *, now: datetime, max_age_days: int
) -> tuple[bool, str]:
    """Decide freshness from the query result. Pure — the tested core.

    Returns (ok, markdown_message). `ok` is False only for a confident stale
    signal; an empty table is *not* a failure (nothing has run yet).
    """
    if not last_run:
        return True, "### ⚠️ Bronze is empty\nNo rows in the registry yet — nothing to check."

    age_days = (now - _parse_ts(last_run)).days
    detail = (
        f"last ingest `{last_run}` ({age_days}d ago); latest statement date `{last_statement_date}`"
    )
    if age_days > max_age_days:
        return False, (
            f"### 🔴 Bronze is STALE — {detail}\n"
            f"Older than the {max_age_days}-day threshold. The bronze job may have stopped "
            "firing (file-arrival triggers don't fire on overwrites — D-018). Check the "
            "Databricks job's recent runs and re-run it if needed (`make run-job`)."
        )
    return True, f"### ✅ Bronze is fresh — {detail}"


def _describe(exc: urllib.error.HTTPError) -> str:
    """Whatever the API said, so a failure names itself instead of arriving as
    a bare ``HTTP Error 400: Bad Request`` (D-088)."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except OSError:
        return "<no response body>"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return " ".join(raw.split())[:300] or "<empty response body>"
    if isinstance(payload, dict):
        return f"{payload.get('error_code', '')}: {payload.get('message', '')}".strip(": ")[:300]
    return json.dumps(payload)[:300]


def _query_last_run(host: str, token: str, warehouse_id: str) -> dict:
    body = {
        "warehouse_id": warehouse_id,
        "catalog": "workspace",
        "schema": "parvum",
        "wait_timeout": "50s",
        "statement": (
            f"SELECT MAX(ingested_at) AS last_run, MAX(statement_date) AS last_stmt "
            f"FROM {_REGISTRY}"
        ),
    }
    for attempt, pause in enumerate((*_BACKOFF_SECONDS, None), start=1):
        request = urllib.request.Request(
            host.rstrip("/") + "/api/2.0/sql/statements",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = _describe(exc)
            if exc.code not in _RETRY_STATUSES or pause is None:
                raise FreshnessUnavailable(
                    f"HTTP {exc.code} after {attempt} attempt(s): {detail}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if pause is None:
                raise FreshnessUnavailable(f"unreachable after {attempt} attempts: {exc}") from exc
        time.sleep(pause)

    raise AssertionError("unreachable: the loop always returns or raises")


def _emit(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        # A non-UTF-8 console (Windows cp1252) chokes on the emoji; the CI
        # runner is UTF-8, but degrade gracefully rather than crash the gate.
        print(message.encode("ascii", "replace").decode("ascii"))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def main() -> None:
    host = os.environ.get("DATABRICKS_HOST", "").strip()
    token = os.environ.get("DATABRICKS_TOKEN", "").strip()
    warehouse = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    max_age_days = int(os.environ.get("FRESHNESS_MAX_AGE_DAYS", _DEFAULT_MAX_AGE_DAYS))

    # Unconfigured is a warning, not a failure: the gate is additive, and a
    # missing secret must not break the feed delivery it rides alongside.
    if not (host and token and warehouse):
        _emit(
            "### ⚠️ Bronze freshness check skipped\n"
            "Set `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `DATABRICKS_WAREHOUSE_ID` "
            "(repo secrets) to enable it."
        )
        return

    try:
        result = _query_last_run(host, token, warehouse)
    except FreshnessUnavailable as exc:
        _emit(
            f"### 🔴 Bronze freshness check could not run\n`{exc}`\n\n"
            "This is a **failure of the check, not a stale-data verdict** — the gate "
            "cannot vouch for bronze either way. It fails the run because a gate that "
            "reports green without checking is how a dead canary goes unnoticed (D-088)."
        )
        sys.exit(1)

    if result.get("status", {}).get("state") != "SUCCEEDED":
        status = json.dumps(result.get("status", {}))[:300]
        _emit(
            f"### 🔴 Bronze freshness query did not succeed\n```\n{status}\n```\n"
            "The gate reached no verdict, so it cannot report green (D-088)."
        )
        sys.exit(1)

    row = (result.get("result", {}).get("data_array") or [[None, None]])[0]
    ok, message = evaluate(row[0], row[1], now=datetime.now(UTC), max_age_days=max_age_days)
    _emit(message)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
