"""MT535 round trip — and the cross-format contrast with semt.002."""

from datetime import date
from decimal import Decimal

import pytest

from parvum_ingest.book import build_book
from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats.mt535 import parse_mt535, render_mt535
from parvum_ingest.formats.semt002 import parse_semt002, render_semt002
from parvum_ingest.model import IdentifierScheme, Money, Position, SecurityIdentifier

AS_OF = date(2026, 7, 15)


def test_rendered_statement_looks_like_swift() -> None:
    book = build_book(AS_OF)
    text = render_mt535(book)
    assert text.startswith(":16R:GENL\n")
    assert ":35B:ISIN US0378331005" in text  # Apple, held in the seed book
    assert ":98A::STAT//20260715" in text
    # One block per position, opened and closed.
    assert text.count(":16R:FIN") == text.count(":16S:FIN") == len(book.positions)


def test_prices_use_the_swift_decimal_comma() -> None:
    # The classic parser trap, asserted as the invariant it is rather than
    # against one security's price — which would only pin the seed book in
    # place and break the next time it legitimately changes.
    price_lines = [ln for ln in render_mt535(build_book(AS_OF)).splitlines() if ln[:5] == ":90B:"]
    assert price_lines
    assert all("." not in line for line in price_lines), "SWIFT amounts never use a decimal point"
    assert any("," in line for line in price_lines)


def test_round_trip_preserves_carried_fields() -> None:
    original = build_book(AS_OF)
    parsed = parse_mt535(render_mt535(original))

    assert parsed.statement_id == original.statement_id
    assert parsed.as_of == original.as_of
    assert parsed.account.account_id == original.account.account_id
    for got, want in zip(parsed.positions, original.positions, strict=True):
        assert got.security == want.security
        assert got.security_name == want.security_name
        assert got.quantity == want.quantity
        assert got.price == want.price
        assert got.price_as_of == want.price_as_of
        assert got.market_value == want.market_value
        # Unlike semt.002, MT535 carries cost basis (via :70E: narrative).
        assert got.cost_basis == want.cost_basis


def test_round_trip_drops_account_details_by_design() -> None:
    # MT535 references the account by id alone; name, custodian BIC and
    # base currency are not part of the message. Enrichment = Phase 2.
    parsed = parse_mt535(render_mt535(build_book(AS_OF)))
    assert parsed.account.name is None
    assert parsed.account.custodian_bic is None
    assert parsed.account.base_currency is None


def test_every_price_survives_the_decimal_comma_exactly() -> None:
    original = build_book(AS_OF)
    parsed = parse_mt535(render_mt535(original))
    round_tripped = {p.security.value: p.price for p in parsed.positions}
    for position in original.positions:
        assert position.price is not None
        assert round_tripped[position.security.value] == position.price, position.security_name


def test_sub_unit_price_keeps_its_leading_zero() -> None:
    # The seed book has held no sub-$1 price since it became 13F-derived, and
    # the leading zero is precisely where a decimal-comma renderer goes wrong
    # (",92" rather than "0,92"). Pinned explicitly so the edge case doesn't
    # depend on whichever securities the seed happens to contain.
    book = build_book(AS_OF)
    penny = Position(
        account_id=book.account.account_id,
        security=SecurityIdentifier(scheme=IdentifierScheme.ISIN, value="GB00BH4HKS39"),
        security_name="Vodafone Group Plc",
        quantity=Decimal("5200"),
        as_of=AS_OF,
        price=Money(amount=Decimal("0.92"), currency="USD"),
        price_as_of=AS_OF,
        market_value=Money(amount=Decimal("4784.00"), currency="USD"),
    )
    text = render_mt535(book.model_copy(update={"positions": (penny,)}))
    assert "ACTU/USD0,92" in text
    assert parse_mt535(text).positions[0].price == penny.price


def test_unbalanced_block_is_rejected() -> None:
    text = render_mt535(build_book(AS_OF)).replace(":16S:GENL\n", "", 1)
    with pytest.raises(FeedParseError, match="block"):
        parse_mt535(text)


def test_xml_input_is_rejected() -> None:
    with pytest.raises(FeedParseError):
        parse_mt535(render_semt002(build_book(AS_OF)))


def test_cross_format_gap_is_complementary() -> None:
    # The same book rendered through both formats: quantities agree
    # perfectly, but each format drops what the other carries. This is the
    # raw material Phase 3 reconciliation is built to work with.
    book = build_book(AS_OF)
    via_semt = parse_semt002(render_semt002(book))
    via_mt = parse_mt535(render_mt535(book))

    for s_pos, m_pos in zip(via_semt.positions, via_mt.positions, strict=True):
        assert s_pos.security == m_pos.security
        assert s_pos.quantity == m_pos.quantity

    assert all(p.cost_basis is None for p in via_semt.positions)  # semt gap
    assert any(p.cost_basis is not None for p in via_mt.positions)  # MT carries it
    assert via_semt.account.name is not None  # semt carries account details
    assert via_mt.account.name is None  # MT gap
