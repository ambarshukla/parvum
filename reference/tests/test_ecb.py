"""ECB rates: parsing, round-trip, and the carry-forward semantics.

All offline. The fixture CSV carries the traps the real file has: newest
row first, an empty USD cell (not published), a pre-floor row that must be
dropped, and a publication gap (weekend) for fill_forward to bridge.
"""

from datetime import date
from decimal import Decimal

import pytest

from parvum_reference.ecb import _parse_history_csv, fill_forward, load_rates, write_rates

# Mimics the real eurofxref-hist.csv shape: Date column + currency columns,
# newest first. 2026-07-04 is a Saturday-shaped hole (no row at all);
# 2026-07-02 has an empty USD cell (row present, rate not published).
FIXTURE_CSV = """Date,USD,JPY,GBP
2026-07-06,1.0921,168.42,0.8511
2026-07-03,1.0899,168.10,0.8503
2026-07-02,,167.95,0.8498
2026-07-01,1.0873,167.80,0.8490
2023-12-31,1.0405,164.00,0.8300
"""


def _rates() -> dict[date, Decimal]:
    return _parse_history_csv(FIXTURE_CSV)


def test_parse_keeps_only_published_usd_rates_after_floor() -> None:
    rates = _rates()
    assert rates == {
        date(2026, 7, 1): Decimal("1.0873"),
        date(2026, 7, 3): Decimal("1.0899"),
        date(2026, 7, 6): Decimal("1.0921"),
    }
    # The empty cell and the pre-floor row are absent, not zero or None.
    assert date(2026, 7, 2) not in rates
    assert date(2023, 12, 31) not in rates


def test_round_trip_through_the_store(tmp_path) -> None:
    out = tmp_path / "fx.json"
    summary = write_rates(_rates(), out)
    assert summary["days"] == 3
    assert summary["first"] == "2026-07-01"
    assert summary["last"] == "2026-07-06"
    assert load_rates(out) == _rates()


def test_fill_forward_bridges_gaps_and_names_its_source() -> None:
    filled = fill_forward(_rates(), date(2026, 7, 1), date(2026, 7, 6))
    # Published days carry their own rate...
    assert filled[date(2026, 7, 1)] == (Decimal("1.0873"), date(2026, 7, 1))
    assert filled[date(2026, 7, 3)] == (Decimal("1.0899"), date(2026, 7, 3))
    # ...gaps carry the last published one, and say which day it came from.
    assert filled[date(2026, 7, 2)] == (Decimal("1.0873"), date(2026, 7, 1))
    assert filled[date(2026, 7, 4)] == (Decimal("1.0899"), date(2026, 7, 3))
    assert filled[date(2026, 7, 5)] == (Decimal("1.0899"), date(2026, 7, 3))
    assert len(filled) == 6


def test_fill_forward_start_may_itself_be_a_gap() -> None:
    filled = fill_forward(_rates(), date(2026, 7, 2), date(2026, 7, 2))
    assert filled[date(2026, 7, 2)] == (Decimal("1.0873"), date(2026, 7, 1))


def test_fill_forward_refuses_an_uncovered_start() -> None:
    with pytest.raises(ValueError, match="no rate on or before"):
        fill_forward(_rates(), date(2026, 6, 1), date(2026, 7, 6))


def test_fill_forward_refuses_inverted_range() -> None:
    with pytest.raises(ValueError, match="after end"):
        fill_forward(_rates(), date(2026, 7, 6), date(2026, 7, 1))
