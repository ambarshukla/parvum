"""One place where the exporter talks to the Databricks SQL Statements API.

Every reader here was hand-rolling the same POST, and every one of them let a
non-2xx response escape as a bare ``urllib`` ``HTTPError``. That loses the
response *body*, which is the only part that says anything useful: Databricks
answers a rejected statement with ``{"error_code": ..., "message": ...}``
naming the cause (an unknown warehouse id, an expired token, a parse error, an
exhausted compute budget). Without it every distinct failure reads identically
as ``HTTP Error 400: Bad Request`` and has to be re-derived by hand.

So the request lives here once, and a failed call is turned into an
``ExportError`` carrying the operation, the status, and whatever the API said.

It also **runs the statement to completion**, which is not the same thing as
getting a 2xx. Submitting sets ``wait_timeout``, and if the statement has not
finished inside that window the API answers 200 with ``{"state": "PENDING"}``
and a ``statement_id`` for the caller to poll -- a documented success, not a
failure. Every reader here used to treat "not SUCCEEDED yet" as "did not
succeed" and give up, which made a cold warehouse indistinguishable from a
broken query (D-091).
"""

import json
import time
import urllib.error
import urllib.request

_STATEMENTS_PATH = "/api/2.0/sql/statements"

# Statuses worth a second attempt, because this API has been observed
# returning them for conditions that clear on their own.
#
# **400 is in this set, and it is the surprising one.** The usual rule is that
# a 4xx is the caller's fault and must never be retried. On 2026-09-03 every
# scheduled reader took an immediate HTTP 400 for at least 100 minutes
# (11:08-12:47 UTC) with unchanged code, unchanged secrets and a warehouse id
# that was demonstrably valid before and after; the identical requests
# succeeded on a manual re-run the same evening. Whatever the workspace was
# doing, it answered well-formed requests with 400 while it did it. Dropping
# 400 from this set to obey the general rule would restore precisely the
# failure the retry exists to absorb -- see D-088 before "fixing" it.
#
# 401/403 (credential) and 404 (no such warehouse) stay out on purpose: those
# are permanent, and retrying them only delays a clear answer.
_RETRY_STATUSES = frozenset({400, 408, 425, 429, 500, 502, 503, 504})

# Four attempts over ~30s. Deliberately modest: it absorbs the blip measured
# in seconds, and does not pretend to ride out an outage measured in hours
# (the 2026-09-03 one would still have failed, correctly, and said why).
_BACKOFF_SECONDS = (2, 8, 20)

# States the API will not move away from on its own. Anything else (PENDING,
# RUNNING) means "ask again".
_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"})

# How long to keep asking. This is sized for a *cold serverless warehouse*,
# not for a slow query: an auto-stopped warehouse must start a cluster before
# it can run anything, and the statement waits in PENDING while it does. That
# start was measured at over six minutes on 2026-09-15, against a 50s
# wait_timeout -- so no single submit can ever cover it, however generous, and
# polling is the only correct shape. Bounded all the same: past this, the
# warehouse is not merely cold and a human should hear about it.
_COMPLETION_BUDGET_SECONDS = 900
_POLL_SECONDS = 5


class ExportError(RuntimeError):
    """The export cannot proceed safely; nothing has been written."""


def _describe(exc: urllib.error.HTTPError) -> str:
    """Databricks' own account of the failure, or a bounded excerpt of
    whatever non-JSON body it sent instead (an HTML proxy error page, say)."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except OSError:  # body already consumed or connection dropped
        return "<no response body>"
    if not raw.strip():
        return "<empty response body>"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return " ".join(raw.split())[:500]
    if isinstance(payload, dict) and ("message" in payload or "error_code" in payload):
        code = payload.get("error_code", "")
        message = payload.get("message", "")
        return f"{code}: {message}".strip(": ")[:500]
    return json.dumps(payload)[:500]


def _statement_error(result: dict) -> str:
    """What the API said about a statement that finished badly."""
    error = result.get("status", {}).get("error") or {}
    code = error.get("error_code", "")
    message = error.get("message", "")
    detail = f"{code}: {message}".strip(": ")
    return detail[:500] or "<no error detail>"


def _call(
    url: str,
    token: str,
    payload: bytes | None,
    *,
    method: str,
    what: str,
    warehouse: str,
    timeout: int,
) -> dict:
    """One call to the API, retrying a transient rejection before giving up."""
    for attempt, pause in enumerate((*_BACKOFF_SECONDS, None), start=1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = _describe(exc)
            retryable = exc.code in _RETRY_STATUSES
            if not retryable or pause is None:
                tried = "" if attempt == 1 else f" after {attempt} attempts"
                raise ExportError(
                    f"{what}: the SQL Statements API returned HTTP {exc.code}{tried} "
                    f"(warehouse {warehouse}). {detail}"
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            # No response at all -- DNS, TLS, connection reset, read timeout.
            if pause is None:
                raise ExportError(
                    f"{what}: could not reach the SQL Statements API after "
                    f"{attempt} attempts (warehouse {warehouse}). {exc}"
                ) from exc
        time.sleep(pause)

    raise AssertionError("unreachable: the loop always returns or raises")


def post_statement(
    host: str,
    token: str,
    body: dict,
    *,
    what: str,
    timeout: int = 90,
    completion_budget: int = _COMPLETION_BUDGET_SECONDS,
) -> dict:
    """Run one statement to completion and return its SUCCEEDED response.

    Submits, then polls while the statement is still PENDING or RUNNING -- the
    submit carries ``wait_timeout``, so a warm warehouse answers inline on the
    first call and never reaches the loop, and a cold one is waited out instead
    of being mistaken for a failure. Retries a transient rejection on every
    call. Returns only a SUCCEEDED response: anything else raises, carrying the
    API's own account of why. ``what`` names the caller's operation so a
    failure says which read broke without walking back up the traceback.
    """
    base = host.rstrip("/") + _STATEMENTS_PATH
    warehouse = body.get("warehouse_id", "<unset>")
    result = _call(
        base,
        token,
        json.dumps(body).encode("utf-8"),
        method="POST",
        what=what,
        warehouse=warehouse,
        timeout=timeout,
    )

    deadline = time.monotonic() + completion_budget
    while (state := result.get("status", {}).get("state")) not in _TERMINAL_STATES:
        statement_id = result.get("statement_id")
        if not statement_id:
            # Non-terminal with nothing to poll: the API has not behaved as
            # documented, and guessing is worse than stopping.
            raise ExportError(
                f"{what}: the SQL Statements API returned state {state!r} with no "
                f"statement_id to poll (warehouse {warehouse})."
            )
        if time.monotonic() >= deadline:
            raise ExportError(
                f"{what}: the statement was still {state} after {completion_budget}s "
                f"(warehouse {warehouse}, statement {statement_id}). A cold serverless "
                "warehouse takes minutes to start, but not this many -- check the "
                "warehouse state before re-running."
            )
        time.sleep(_POLL_SECONDS)
        result = _call(
            f"{base}/{statement_id}",
            token,
            None,
            method="GET",
            what=what,
            warehouse=warehouse,
            timeout=timeout,
        )

    if state != "SUCCEEDED":
        raise ExportError(
            f"{what}: the statement finished as {state} (warehouse {warehouse}). "
            f"{_statement_error(result)}"
        )
    return result
