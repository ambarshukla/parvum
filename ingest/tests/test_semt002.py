"""semt.002 round trip: what goes in must come out — minus what the
format cannot carry, which the tests document explicitly."""

from datetime import date

import pytest

from parvum_ingest.book import build_book
from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats.semt002 import parse_semt002, render_semt002

AS_OF = date(2026, 7, 15)


def test_rendered_statement_looks_like_iso20022() -> None:
    xml = render_semt002(build_book(AS_OF))
    assert xml.startswith("<?xml")
    assert "urn:iso:std:iso:20022:tech:xsd:semt.002.001.11" in xml
    assert "<SctiesBalCtdyRpt>" in xml
    assert xml.count("<BalForAcct>") == len(build_book(AS_OF).positions)


def test_round_trip_preserves_carried_fields() -> None:
    original = build_book(AS_OF)
    parsed = parse_semt002(render_semt002(original))

    assert parsed.statement_id == original.statement_id
    assert parsed.account == original.account
    assert parsed.as_of == original.as_of
    for got, want in zip(parsed.positions, original.positions, strict=True):
        assert got.security == want.security
        assert got.security_name == want.security_name
        assert got.quantity == want.quantity
        assert got.price == want.price
        assert got.price_as_of == want.price_as_of
        assert got.market_value == want.market_value


def test_round_trip_drops_cost_basis_by_design() -> None:
    # The semt.002 subset does not carry acquisition cost — like many real
    # custody statements. The gap is a property of the format, not a bug,
    # and reconciliation (Phase 3) must expect it.
    original = build_book(AS_OF)
    assert any(p.cost_basis is not None for p in original.positions)
    parsed = parse_semt002(render_semt002(original))
    assert all(p.cost_basis is None for p in parsed.positions)


def test_not_xml_is_rejected() -> None:
    with pytest.raises(FeedParseError, match="not well-formed"):
        parse_semt002(":16R:GENL\nthis is MT535, not XML")


def test_truncated_file_is_rejected() -> None:
    xml = render_semt002(build_book(AS_OF))
    with pytest.raises(FeedParseError):
        parse_semt002(xml[: len(xml) // 2])


def test_missing_required_element_is_named_in_the_error() -> None:
    xml = (
        render_semt002(build_book(AS_OF))
        .replace("<StmtId>", "<WrongId>")
        .replace("</StmtId>", "</WrongId>")
    )
    with pytest.raises(FeedParseError, match="StmtId"):
        parse_semt002(xml)
