"""PDF rendering: a valid PDF comes out, and the real figures a human or an
LLM would read are actually present in its extracted text — not just
"a PDF got produced," which would prove nothing about content fidelity."""

from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.model import FundCommitment
from parvum_alts_hitl.render import (
    DRAWDOWN,
    EURO,
    PLAIN,
    render_capital_account_statement,
    render_capital_call,
    render_distribution,
)

COMMITMENT = FundCommitment(
    fund_id="FUND-TEST01",
    fund_name="Test Capital Partners I",
    account_id="TEST-ACC",
    currency="USD",
    vintage_year=2024,
    total_commitment=Decimal("1000000.00"),
)


def _text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_capital_call_pdf_contains_the_real_figures() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    text = _text(render_capital_call(call))
    assert call.fund_name in text
    assert "Capital Call Notice" in text
    assert call.account_id in text
    assert f"{call.call_amount:,.2f}" in text
    assert call.purpose in text


def test_distribution_pdf_contains_the_real_figures() -> None:
    distribution = build_fund_book(COMMITMENT).distributions[0]
    text = _text(render_distribution(distribution))
    assert distribution.fund_name in text
    assert "Distribution Notice" in text
    assert f"{distribution.distribution_amount:,.2f}" in text
    assert distribution.source is not None
    assert distribution.source.value in text


def test_capital_account_statement_pdf_contains_the_real_figures() -> None:
    statement = build_fund_book(COMMITMENT).statements[2]
    text = _text(render_capital_account_statement(statement))
    assert statement.fund_name in text
    assert statement.period_end.isoformat() in text
    assert f"{statement.ending_balance:,.2f}" in text


def test_a_missing_purpose_does_not_appear_as_the_word_none() -> None:
    call = build_fund_book(COMMITMENT).calls[0].model_copy(update={"purpose": None})
    text = _text(render_capital_call(call))
    assert "Purpose" not in text


def test_the_drawdown_template_uses_different_vocabulary_for_the_same_fields() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    text = _text(render_capital_call(call, DRAWDOWN))
    assert "Drawdown Notice" in text
    assert "Drawdown Amount" in text
    assert "Capital Call Notice" not in text
    # The underlying figure is unchanged by which template reads it out --
    # only the label around it varies.
    assert f"{call.call_amount:,.2f}" in text


EUR_COMMITMENT = COMMITMENT.model_copy(update={"currency": "EUR"})


def test_the_euro_template_formats_money_and_dates_in_the_european_convention() -> None:
    call = build_fund_book(EUR_COMMITMENT).calls[0]
    text = _text(render_capital_call(call, EURO))
    assert "Capital Contribution Notice" in text
    # European grouping/decimal marks are the reverse of Python's default
    # formatting -- assert the actual swapped string, not a US-style one.
    assert EURO.money(call.call_amount) in text
    assert f"{call.call_amount:,.2f}" not in text
    # DD/MM/YYYY, not ISO.
    assert call.call_date.strftime("%d/%m/%Y") in text
    assert call.call_date.isoformat() not in text


def test_every_template_extracts_without_encoding_replacement_characters() -> None:
    # Regression test: reportlab's standard fonts have no embedded
    # ToUnicode mapping for non-ASCII characters (the euro sign, an
    # em-dash), so pypdf's extractor silently produced U+FFFD in their
    # place -- exactly the kind of corruption that would feed garbage to
    # the LLM extraction step without ever raising an error.
    book = build_fund_book(EUR_COMMITMENT)
    texts = [
        _text(render_capital_call(book.calls[0], EURO)),
        _text(render_distribution(book.distributions[0], EURO)),
        _text(render_capital_account_statement(book.statements[0], EURO)),
        _text(render_capital_call(build_fund_book(COMMITMENT).calls[0], PLAIN)),
    ]
    for text in texts:
        assert "�" not in text
