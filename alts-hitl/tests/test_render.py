"""PDF rendering: a valid PDF comes out, and the real figures a human or an
LLM would read are actually present in its extracted text — not just
"a PDF got produced," which would prove nothing about content fidelity."""

from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.model import FundCommitment
from parvum_alts_hitl.render import (
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
