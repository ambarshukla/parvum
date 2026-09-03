"""The bronze freshness gate's decision logic (pure, offline)."""

import io
import urllib.error
from datetime import UTC, datetime

import pytest

from parvum_ingest import freshness
from parvum_ingest.freshness import evaluate

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def test_recent_ingest_is_fresh() -> None:
    ok, msg = evaluate("2026-07-16T06:20:00Z", "2026-07-16", now=NOW, max_age_days=4)
    assert ok
    assert "fresh" in msg.lower()


def test_old_ingest_is_stale_and_fails() -> None:
    # Bronze last ran 10 days ago — the job has gone dark.
    ok, msg = evaluate("2026-07-07T06:20:00Z", "2026-07-07", now=NOW, max_age_days=4)
    assert not ok
    assert "STALE" in msg
    assert "D-018" in msg  # points at the likely cause


def test_the_threshold_boundary() -> None:
    # Exactly at the threshold passes; one day past fails.
    at = evaluate("2026-07-13T12:00:00Z", "2026-07-13", now=NOW, max_age_days=4)  # 4 days
    past = evaluate("2026-07-12T12:00:00Z", "2026-07-12", now=NOW, max_age_days=4)  # 5 days
    assert at[0] is True
    assert past[0] is False


def test_empty_registry_is_not_a_failure() -> None:
    # Nothing has run yet — a warning, not an alarm that wakes someone.
    ok, msg = evaluate(None, None, now=NOW, max_age_days=4)
    assert ok
    assert "empty" in msg.lower()


def test_space_separated_timestamp_is_accepted() -> None:
    # Databricks may return 'YYYY-MM-DD HH:MM:SS' instead of ISO 'T'.
    ok, _ = evaluate("2026-07-16 06:20:00", "2026-07-16", now=NOW, max_age_days=4)
    assert ok


# --- the transport layer: retry, and refusing to report green blind (D-088) --


def _drive(monkeypatch, *outcomes):
    """Script urlopen's responses; no real backoff."""
    monkeypatch.setattr(freshness.time, "sleep", lambda seconds: None)
    remaining = list(outcomes)

    def fake_urlopen(request, timeout=None):
        outcome = remaining.pop(0)
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(
                request.full_url, outcome, "err", {}, io.BytesIO(b'{"message": "transient"}')
            )
        return io.BytesIO(outcome)

    monkeypatch.setattr(freshness.urllib.request, "urlopen", fake_urlopen)


def test_a_transient_400_is_retried_rather_than_giving_up(monkeypatch) -> None:
    # Exactly the 2026-09-03 shape, which this gate previously swallowed whole.
    _drive(monkeypatch, 400, b'{"status": {"state": "SUCCEEDED"}}')
    assert freshness._query_last_run("https://h", "t", "w")["status"]["state"] == "SUCCEEDED"


def test_a_persistent_400_becomes_unavailable_not_a_shrug(monkeypatch) -> None:
    _drive(monkeypatch, 400, 400, 400, 400)
    with pytest.raises(freshness.FreshnessUnavailable) as caught:
        freshness._query_last_run("https://h", "t", "w")
    assert "HTTP 400" in str(caught.value)
    assert "transient" in str(caught.value)  # the API's own words reach the operator


def test_a_credential_failure_is_not_retried(monkeypatch) -> None:
    _drive(monkeypatch, 403)
    with pytest.raises(freshness.FreshnessUnavailable):
        freshness._query_last_run("https://h", "t", "w")


def test_an_unanswerable_gate_fails_the_run_instead_of_reporting_green(monkeypatch) -> None:
    """The regression this whole slice exists for: on 2026-09-03 the daily run
    went green having never checked freshness at all."""
    _drive(monkeypatch, 400, 400, 400, 400)
    monkeypatch.setenv("DATABRICKS_HOST", "https://h")
    monkeypatch.setenv("DATABRICKS_TOKEN", "t")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "w")
    said: list[str] = []
    monkeypatch.setattr(freshness, "_emit", said.append)

    with pytest.raises(SystemExit) as caught:
        freshness.main()

    assert caught.value.code == 1
    assert "could not run" in said[0]
    # "could not run" must not be mistaken for a stale-data verdict.
    assert "not a stale-data verdict" in said[0]
    assert "STALE" not in said[0]


def test_unconfigured_secrets_remain_a_warning_not_a_failure(monkeypatch) -> None:
    """A setup state, deliberately still non-fatal — unlike a gate that goes
    blind mid-flight."""
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    said: list[str] = []
    monkeypatch.setattr(freshness, "_emit", said.append)

    freshness.main()  # returns, does not raise SystemExit

    assert "skipped" in said[0]
