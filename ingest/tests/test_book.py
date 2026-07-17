"""The seed book must be deterministic, internally consistent, and real."""

from datetime import date
from decimal import Decimal

import pytest

from parvum_ingest.book import build_book, build_cash_statement
from parvum_ingest.edgar import EdgarError
from parvum_reference.accounts import UNIVERSE

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


# --- the account universe --------------------------------------------------


def _isins(spec) -> dict[str, str]:
    return {p.security_name: p.security.value for p in build_book(AS_OF, spec).positions}


def test_canadian_cross_listings_get_their_real_isins() -> None:
    # The trap that forced the curated domicile slice: Canadian issuers carry
    # numeric, US-looking CUSIPs. These are the issuers' real published
    # ISINs — a default-US derivation would have minted US1363751029 etc.,
    # identifiers that exist nowhere yet pass our own checksum.
    gates = _isins(next(s for s in UNIVERSE if s.account_id == "FQ5521"))
    pershing = _isins(next(s for s in UNIVERSE if s.account_id == "X4478210"))
    assert gates["CANADIAN NATL RY CO"] == "CA1363751027"
    assert pershing["BROOKFIELD CORP"] == "CA11271J1075"
    assert pershing["RESTAURANT BRANDS INTL INC"] == "CA76131D1033"


def test_us_names_still_derive_us_isins() -> None:
    gates = _isins(next(s for s in UNIVERSE if s.account_id == "FQ5521"))
    assert gates["MICROSOFT CORP"] == "US5949181045"


def test_the_waste_pair_lands_on_opposite_sides_of_the_border() -> None:
    # Two waste companies, CUSIPs one character apart, different countries:
    # Waste Management (94106L109) is US; Waste Connections (94106B101)
    # redomiciled to Canada in 2016. The fetch-time audit caught the second —
    # the curated map had missed it — so this pins both, against the issuers'
    # real ISINs.
    from parvum_ingest.model import isin_from_cusip
    from parvum_reference.domicile import domicile_of

    assert domicile_of("94106L109") == "US"
    assert domicile_of("94106B101") == "CA"
    assert isin_from_cusip("94106L109", country="US").value == "US94106L1098"
    assert isin_from_cusip("94106B101", country="CA").value == "CA94106B1013"


def test_same_filer_two_accounts_differ_only_in_scale() -> None:
    growth = build_book(AS_OF, next(s for s in UNIVERSE if s.account_id == "60011234"))
    retirement = build_book(AS_OF, next(s for s in UNIVERSE if s.account_id == "60018852"))
    assert {p.security.value for p in growth.positions} == {
        p.security.value for p in retirement.positions
    }
    g = {p.security.value: p.quantity for p in growth.positions}
    r = {p.security.value: p.quantity for p in retirement.positions}
    # Divisors 10k vs 20k: the retirement account holds about half throughout.
    assert all(r[isin] <= g[isin] for isin in g)


def test_cost_basis_differs_between_accounts_holding_the_same_name() -> None:
    # Two accounts bought the same security at different times; identical
    # cost bases across the universe would be a fingerprint no real book has.
    growth = build_book(AS_OF, next(s for s in UNIVERSE if s.account_id == "60011234"))
    retirement = build_book(AS_OF, next(s for s in UNIVERSE if s.account_id == "60018852"))
    g = {p.security.value: p.cost_basis for p in growth.positions}
    r = {p.security.value: p.cost_basis for p in retirement.positions}
    both = [i for i in g if g[i] is not None and r[i] is not None]
    assert both and any(g[i] != r[i] for i in both)


def test_cash_statement_follows_the_account() -> None:
    eur_spec = next(s for s in UNIVERSE if s.account_id == "FQ5521")
    stmt = build_cash_statement(AS_OF, eur_spec)
    assert stmt.account.account_id == "FQ5521"
    assert all(e.amount.currency == "EUR" for e in stmt.entries)
    # Descriptions name securities this account actually holds.
    dividend = next(e for e in stmt.entries if e.type.name == "DIVIDEND")
    held = {p.security_name.title() for p in build_book(AS_OF, eur_spec).positions}
    assert any(name in dividend.description for name in held)
