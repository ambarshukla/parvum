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


def post_statement(host: str, token: str, body: dict, *, what: str, timeout: int = 90) -> dict:
    """Submit one statement and return the decoded response.

    Retries a transient rejection a few times before giving up. ``what`` names
    the caller's operation so a failure says which read broke without the
    reader having to walk back up the traceback.
    """
    url = host.rstrip("/") + _STATEMENTS_PATH
    payload = json.dumps(body).encode("utf-8")
    warehouse = body.get("warehouse_id", "<unset>")

    for attempt, pause in enumerate((*_BACKOFF_SECONDS, None), start=1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
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
