"""The SQL Statements API's own account of a failure must reach the operator.

Every reader used to let a non-2xx escape as a bare ``HTTPError``, so an
unknown warehouse, an expired token and a parse error all read identically as
``HTTP Error 400: Bad Request``. These pin the body actually surfacing.
"""

import io
import json
import urllib.error

import pytest

from parvum_export import sql_api
from parvum_export.sql_api import ExportError, post_statement

BODY = {"warehouse_id": "0fb6ed828ed1e874", "statement": "SELECT 1"}


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """400 is retryable (D-088), so every failing case here would otherwise
    sit through the real ~30s backoff."""
    monkeypatch.setattr(sql_api.time, "sleep", lambda seconds: None)


def _raise(payload: bytes, code: int = 400):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "Bad Request", {}, io.BytesIO(payload))

    return fake_urlopen


def test_databricks_error_code_and_message_reach_the_operator(monkeypatch):
    payload = json.dumps(
        {"error_code": "INVALID_PARAMETER_VALUE", "message": "No warehouse with id abc"}
    ).encode()
    monkeypatch.setattr(sql_api.urllib.request, "urlopen", _raise(payload))

    with pytest.raises(ExportError) as caught:
        post_statement("https://example.invalid", "tok", BODY, what="reading gold_client_wealth")

    message = str(caught.value)
    assert "reading gold_client_wealth" in message
    assert "HTTP 400" in message
    assert "INVALID_PARAMETER_VALUE" in message
    assert "No warehouse with id abc" in message
    # The warehouse id is the most common cause of a 400 here, so it is named
    # even when the API's own message does not mention it.
    assert "0fb6ed828ed1e874" in message


def test_the_original_httperror_is_kept_as_the_cause(monkeypatch):
    monkeypatch.setattr(sql_api.urllib.request, "urlopen", _raise(b"{}", code=403))
    with pytest.raises(ExportError) as caught:
        post_statement("https://example.invalid", "tok", BODY, what="reading x")
    assert isinstance(caught.value.__cause__, urllib.error.HTTPError)
    assert "HTTP 403" in str(caught.value)


def test_a_non_json_body_is_excerpted_rather_than_lost(monkeypatch):
    # A proxy or gateway in front of the workspace answers in HTML, not JSON.
    monkeypatch.setattr(
        sql_api.urllib.request,
        "urlopen",
        _raise(b"<html>\n  <body>502 upstream   timeout</body>\n</html>", code=502),
    )
    with pytest.raises(ExportError) as caught:
        post_statement("https://example.invalid", "tok", BODY, what="reading x")
    assert "502 upstream timeout" in str(caught.value)


def test_an_empty_body_says_so_instead_of_looking_like_success(monkeypatch):
    monkeypatch.setattr(sql_api.urllib.request, "urlopen", _raise(b"   "))
    with pytest.raises(ExportError) as caught:
        post_statement("https://example.invalid", "tok", BODY, what="reading x")
    assert "empty response body" in str(caught.value)


def test_the_bearer_token_never_appears_in_the_error(monkeypatch):
    monkeypatch.setattr(sql_api.urllib.request, "urlopen", _raise(b'{"message": "nope"}'))
    with pytest.raises(ExportError) as caught:
        post_statement("https://example.invalid", "s3cret-token", BODY, what="reading x")
    assert "s3cret-token" not in str(caught.value)


def _sequence(monkeypatch, *outcomes):
    """Drive urlopen through a fixed script of responses; no real sleeping."""
    calls = []
    monkeypatch.setattr(sql_api.time, "sleep", lambda seconds: calls.append(seconds))

    remaining = list(outcomes)

    def fake_urlopen(request, timeout=None):
        outcome = remaining.pop(0)
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(
                request.full_url, outcome, "err", {}, io.BytesIO(b'{"message": "transient"}')
            )
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)

    monkeypatch.setattr(sql_api.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_a_transient_400_is_retried_and_then_succeeds(monkeypatch):
    # The 2026-09-03 shape: the API rejects a well-formed request, then stops.
    slept = _sequence(monkeypatch, 400, 400, b'{"status": {"state": "SUCCEEDED"}}')
    assert (
        post_statement("https://h", "t", BODY, what="reading x")["status"]["state"] == "SUCCEEDED"
    )
    assert slept == [2, 8]


def test_a_persistent_400_still_fails_and_says_how_many_attempts(monkeypatch):
    _sequence(monkeypatch, 400, 400, 400, 400)
    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading x")
    assert "after 4 attempts" in str(caught.value)
    assert "transient" in str(caught.value)


@pytest.mark.parametrize("code", [401, 403, 404])
def test_a_permanent_failure_is_not_retried(monkeypatch, code):
    # Credentials and a missing warehouse will not fix themselves; retrying
    # them only delays a clear answer.
    slept = _sequence(monkeypatch, code)
    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading x")
    assert slept == []
    assert "after" not in str(caught.value)


def test_a_network_failure_is_retried_then_reported(monkeypatch):
    err = urllib.error.URLError("connection reset")
    _sequence(monkeypatch, err, err, err, err)
    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading x")
    assert "could not reach" in str(caught.value)
    assert "connection reset" in str(caught.value)


def test_a_successful_response_is_decoded_and_returned(monkeypatch):
    def fake_urlopen(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer tok"
        assert json.loads(request.data) == BODY
        return io.BytesIO(b'{"status": {"state": "SUCCEEDED"}}')

    monkeypatch.setattr(sql_api.urllib.request, "urlopen", fake_urlopen)
    assert post_statement("https://example.invalid/", "tok", BODY, what="reading x") == {
        "status": {"state": "SUCCEEDED"}
    }


# --- Running the statement to completion (D-091) --------------------------
#
# A submit carrying wait_timeout answers 200 with state PENDING when the
# statement has not finished in time, handing back a statement_id to poll.
# Reading that as "did not succeed" is what took the daily feed gate and
# export-gold down on 2026-09-15 against a perfectly healthy warehouse that
# was merely cold (a 6m03s start, measured).

PENDING = b'{"statement_id": "abc-123", "status": {"state": "PENDING"}}'
RUNNING = b'{"statement_id": "abc-123", "status": {"state": "RUNNING"}}'
DONE = b'{"statement_id": "abc-123", "status": {"state": "SUCCEEDED"}, "result": {"row_count": 1}}'


def _record_requests(monkeypatch):
    """Capture the requests made, so the poll's shape can be asserted."""
    seen = []
    original = sql_api.urllib.request.urlopen

    def spy(request, timeout=None):
        seen.append((request.get_method(), request.full_url))
        return original(request, timeout)

    monkeypatch.setattr(sql_api.urllib.request, "urlopen", spy)
    return seen


def test_a_pending_statement_is_polled_until_it_succeeds(monkeypatch):
    slept = _sequence(monkeypatch, PENDING, RUNNING, DONE)
    seen = _record_requests(monkeypatch)

    result = post_statement("https://h", "t", BODY, what="reading x")

    assert result["status"]["state"] == "SUCCEEDED"
    assert result["result"]["row_count"] == 1
    # One submit, then two polls against the statement's own URL.
    assert seen == [
        ("POST", "https://h/api/2.0/sql/statements"),
        ("GET", "https://h/api/2.0/sql/statements/abc-123"),
        ("GET", "https://h/api/2.0/sql/statements/abc-123"),
    ]
    assert slept == [sql_api._POLL_SECONDS, sql_api._POLL_SECONDS]


def test_a_warm_warehouse_answers_inline_and_is_never_polled(monkeypatch):
    # The common path must cost no extra round trip.
    _sequence(monkeypatch, DONE)
    seen = _record_requests(monkeypatch)
    post_statement("https://h", "t", BODY, what="reading x")
    assert [method for method, _ in seen] == ["POST"]


def test_a_statement_that_finishes_badly_reports_the_apis_own_reason(monkeypatch):
    failed = json.dumps(
        {
            "statement_id": "abc-123",
            "status": {
                "state": "FAILED",
                "error": {"error_code": "TABLE_OR_VIEW_NOT_FOUND", "message": "no such table t"},
            },
        }
    ).encode()
    _sequence(monkeypatch, failed)

    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading gold_client_wealth")

    message = str(caught.value)
    assert "finished as FAILED" in message
    assert "TABLE_OR_VIEW_NOT_FOUND" in message
    assert "no such table t" in message
    assert "reading gold_client_wealth" in message


def test_the_poll_is_bounded_and_says_what_to_look_at(monkeypatch):
    # Never-ending PENDING: the budget must stop it rather than hang the job.
    # The clock is faked so the budget is reached without real waiting -- and
    # so the test pins the budget itself, not the number of canned responses.
    now = [0.0]
    monkeypatch.setattr(sql_api.time, "monotonic", lambda: now[0])
    _sequence(monkeypatch, *([PENDING] * 500))
    monkeypatch.setattr(sql_api.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading x", completion_budget=30)
    message = str(caught.value)
    assert "still PENDING after 30s" in message
    assert "abc-123" in message
    assert "warehouse" in message


def test_a_non_terminal_state_with_nothing_to_poll_stops_rather_than_guessing(monkeypatch):
    _sequence(monkeypatch, b'{"status": {"state": "PENDING"}}')
    with pytest.raises(ExportError) as caught:
        post_statement("https://h", "t", BODY, what="reading x")
    assert "no statement_id to poll" in str(caught.value)


def test_a_transient_failure_during_polling_is_retried_not_fatal(monkeypatch):
    # The retry policy has to cover the polls too, not just the submit.
    _sequence(monkeypatch, PENDING, 503, DONE)
    result = post_statement("https://h", "t", BODY, what="reading x")
    assert result["status"]["state"] == "SUCCEEDED"
