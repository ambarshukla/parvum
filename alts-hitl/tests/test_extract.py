"""Extraction logic, tested against a mocked Anthropic client so the test
suite never makes a real (billed) API call — only `make alts-extract`/
`make alts-eval` do that, deliberately outside CI."""

import types
from decimal import Decimal
from unittest.mock import MagicMock

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.extract import extract_document, pdf_text, self_consistency_ok
from parvum_alts_hitl.model import FundCommitment
from parvum_alts_hitl.render import render_capital_call

COMMITMENT = FundCommitment(
    fund_id="FUND-TEST01",
    fund_name="Test Capital Partners I",
    account_id="TEST-ACC",
    currency="USD",
    vintage_year=2024,
    total_commitment=Decimal("1000000.00"),
)


def _fake_response(input_dict: dict):
    block = types.SimpleNamespace(type="tool_use", input=input_dict)
    return types.SimpleNamespace(content=[block])


def test_pdf_text_contains_the_real_figures() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    text = pdf_text(render_capital_call(call))
    assert call.fund_name in text
    assert f"{call.call_amount:,.2f}" in text


def test_statement_reconciling_is_self_consistent() -> None:
    fields = {
        "beginning_balance": "0",
        "contributions": "100000.00",
        "distributions": "0",
        "management_fees": "0",
        "realized_gain_loss": "0",
        "unrealized_gain_loss": "0",
        "ending_balance": "100000.00",
    }
    assert self_consistency_ok("capital_account_statement", fields) is True


def test_statement_not_reconciling_is_not_self_consistent() -> None:
    fields = {
        "beginning_balance": "0",
        "contributions": "100000.00",
        "distributions": "0",
        "management_fees": "0",
        "realized_gain_loss": "0",
        "unrealized_gain_loss": "0",
        "ending_balance": "999.00",
    }
    assert self_consistency_ok("capital_account_statement", fields) is False


def test_statement_missing_a_field_is_not_self_consistent() -> None:
    assert self_consistency_ok("capital_account_statement", {"beginning_balance": "0"}) is False


def test_call_with_all_amounts_present_is_self_consistent() -> None:
    fields = {
        "call_amount": "100.00",
        "cumulative_called": "100.00",
        "remaining_commitment": "900.00",
    }
    assert self_consistency_ok("capital_call", fields) is True


def test_call_missing_an_amount_is_not_self_consistent() -> None:
    fields = {
        "call_amount": None,
        "cumulative_called": "100.00",
        "remaining_commitment": "900.00",
    }
    assert self_consistency_ok("capital_call", fields) is False


def test_extract_document_keeps_self_reported_confidence_when_consistent() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {
            "fund_name": call.fund_name,
            "account_id": call.account_id,
            "call_number": call.call_number,
            "call_date": call.call_date.isoformat(),
            "due_date": call.due_date.isoformat(),
            "call_amount": str(call.call_amount),
            "cumulative_called": str(call.cumulative_called),
            "remaining_commitment": str(call.remaining_commitment),
            "purpose": call.purpose,
            "confidence": 0.95,
        }
    )

    result = extract_document(client, render_capital_call(call), "capital_call")

    assert result.self_reported_confidence == 0.95
    assert result.self_consistent is True
    assert result.confidence == 0.95
    assert result.fields["call_amount"] == str(call.call_amount)
    assert "confidence" not in result.fields  # popped out into its own field


def test_extract_document_caps_confidence_when_inconsistent() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {
            "fund_name": call.fund_name,
            "account_id": call.account_id,
            "call_number": call.call_number,
            "call_date": call.call_date.isoformat(),
            "due_date": call.due_date.isoformat(),
            "call_amount": None,  # missing -> not self-consistent
            "cumulative_called": str(call.cumulative_called),
            "remaining_commitment": str(call.remaining_commitment),
            "purpose": call.purpose,
            "confidence": 0.9,
        }
    )

    result = extract_document(client, render_capital_call(call), "capital_call")

    assert result.self_consistent is False
    assert result.confidence == 0.5  # min(0.9, 0.5)


def test_extract_document_forces_the_right_tool_for_the_doc_type() -> None:
    call = build_fund_book(COMMITMENT).calls[0]
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {
            "fund_name": call.fund_name,
            "account_id": call.account_id,
            "call_number": 1,
            "call_date": "2024-03-31",
            "due_date": "2024-04-14",
            "call_amount": "1.00",
            "cumulative_called": "1.00",
            "remaining_commitment": "1.00",
            "purpose": None,
            "confidence": 0.5,
        }
    )

    extract_document(client, render_capital_call(call), "capital_call")

    _, kwargs = client.messages.create.call_args
    assert kwargs["tool_choice"] == {"type": "tool", "name": "extract_capital_call"}
