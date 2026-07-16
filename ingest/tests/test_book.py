"""The seed book must be deterministic, internally consistent, and real."""

from datetime import date
from decimal import Decimal

from parvum_ingest.book import build_book

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
