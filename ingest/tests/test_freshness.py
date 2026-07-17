"""The bronze freshness gate's decision logic (pure, offline)."""

from datetime import UTC, datetime

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
