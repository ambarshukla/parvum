"""camt.053 round trip, the closing-balance invariant, and cross-message
namespace checking."""

from datetime import date
from decimal import Decimal

import pytest

from parvum_ingest.book import build_book, build_cash_statement
from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats.camt053 import DEBIT_TYPES, parse_camt053, render_camt053
from parvum_ingest.formats.semt002 import render_semt002
from parvum_ingest.model import BalanceType

AS_OF = date(2026, 7, 15)


def test_clean_cash_book_balances_explain_the_movement() -> None:
    # The invariant reconciliation will lean on: closing = opening + net.
    stmt = build_cash_statement(AS_OF)
    opening = next(b for b in stmt.balances if b.balance_type is BalanceType.OPENING)
    closing = next(b for b in stmt.balances if b.balance_type is BalanceType.CLOSING)
    net = sum(
        (-t.amount.amount if t.type in DEBIT_TYPES else t.amount.amount) for t in stmt.entries
    )
    assert closing.balance.amount == opening.balance.amount + net
    # Pinned deliberately: the invariant above is self-consistent by
    # construction, so it would still hold if the seed changed by accident.
    assert closing.balance.amount == Decimal("54234.95")


def test_rendered_statement_looks_like_camt053() -> None:
    xml = render_camt053(build_cash_statement(AS_OF))
    assert "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08" in xml
    assert "<BkToCstmrStmt>" in xml
    assert "<Cd>OPBD</Cd>" in xml and "<Cd>CLBD</Cd>" in xml
    assert xml.count("<Ntry>") == 6
    # Direction comes from the transaction type: a BUY is cash out.
    assert "<CdtDbtInd>DBIT</CdtDbtInd>" in xml


def test_round_trip_preserves_everything_it_carries() -> None:
    original = build_cash_statement(AS_OF)
    parsed = parse_camt053(render_camt053(original))

    assert parsed.statement_id == original.statement_id
    assert parsed.account == original.account  # camt carries full account details
    assert parsed.as_of == original.as_of
    assert parsed.balances == original.balances
    assert parsed.entries == original.entries  # incl. type, both dates, description


def test_unknown_proprietary_code_is_rejected() -> None:
    xml = render_camt053(build_cash_statement(AS_OF)).replace(
        "<Cd>DIVIDEND</Cd>", "<Cd>DIV-XX</Cd>"
    )
    # An unmappable transaction code means we cannot classify the entry at
    # all — structural, not a plausibility issue, hence a parse error.
    with pytest.raises(FeedParseError, match="DIV-XX"):
        parse_camt053(xml)


def test_wrong_message_type_is_rejected_by_namespace() -> None:
    # A semt.002 document is well-formed XML with root <Document> too — the
    # namespace is what identifies WHICH message it is.
    with pytest.raises(FeedParseError, match="unexpected root"):
        parse_camt053(render_semt002(build_book(AS_OF)))


def test_statement_without_balances_is_rejected() -> None:
    xml = render_camt053(build_cash_statement(AS_OF))
    start = xml.index("<Bal>")
    end = xml.rindex("</Bal>") + len("</Bal>")
    with pytest.raises(FeedParseError, match="no balances"):
        parse_camt053(xml[:start] + xml[end:])
