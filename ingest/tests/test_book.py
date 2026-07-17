"""The seed book must be deterministic, internally consistent, and real."""

from datetime import date
from decimal import Decimal

import pytest

from parvum_ingest.book import build_book
from parvum_ingest.edgar import EdgarError

AS_OF = date(2026, 7, 15)


def test_same_input_same_book() -> None:
    # Determinism is what makes round-trip tests and defect injection stable.
    assert build_book(AS_OF) == build_book(AS_OF)


def test_all_isins_are_real() -> None:
    for pos in build_book(AS_OF).positions:
        assert pos.security.has_valid_checksum(), pos.security.value


def test_market_value_is_quantity_times_price() -> None:
    for pos in build_book(AS_OF).positions:
        assert pos.price is not None and pos.market_value is not None
        expected = (pos.quantity * pos.price.amount).quantize(Decimal("0.01"))
        assert pos.market_value.amount == expected, pos.security_name


def test_clean_book_has_sparse_cost_basis() -> None:
    # Even the defect-free book has gaps — sparse optional data is normal.
    missing = [p for p in build_book(AS_OF).positions if p.cost_basis is None]
    assert 0 < len(missing) < len(build_book(AS_OF).positions)


# --- point-in-time: the book follows the filing that was public ------------
# Fixture store: Q4-2025 filed 2026-02-17; Q1-2026 filed 2026-05-15.


def test_book_changes_at_the_filing_boundary() -> None:
    before = {p.security_name for p in build_book(date(2026, 5, 14)).positions}
    after = {p.security_name for p in build_book(date(2026, 5, 15)).positions}
    assert "CITIGROUP INC" in before and "CITIGROUP INC" not in after
    assert "ALPHABET INC" in after and "ALPHABET INC" not in before


def test_book_is_stable_within_a_filing_regime() -> None:
    # Positions are identical across the regime; only the statement dates
    # move. A new filing must never rewrite days before its own filing date.
    in_march = build_book(date(2026, 3, 10)).positions
    in_april = build_book(date(2026, 4, 20)).positions
    strip = lambda ps: [p.model_dump(exclude={"as_of", "price_as_of"}) for p in ps]  # noqa: E731
    assert strip(in_march) == strip(in_april)


def test_dates_before_any_public_filing_refuse_loudly() -> None:
    # No filing was public on 2026-02-16, so no book can honestly exist.
    with pytest.raises(EdgarError, match="was public by"):
        build_book(date(2026, 2, 16))


def test_cins_holdings_never_reach_the_book() -> None:
    # Chubb (CINS H1467J104) is in the Q1 fixture filing; deriving a "US"
    # ISIN for it would fabricate an identifier (D-014).
    assert not any("CHUBB" in p.security_name for p in build_book(AS_OF).positions)
