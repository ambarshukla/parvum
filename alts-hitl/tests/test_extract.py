"""Extraction logic, tested at two layers:

- `AnthropicProvider`/`OpenRouterProvider.extract()` against a mocked SDK
  client each, proving the request-shape/response-parsing translation for
  that provider specifically (this is the only provider-specific code in
  the module).
- `extract_document()` against a small fake `LLMProvider` implementing the
  interface directly — the hybrid-confidence/self-consistency logic is
  provider-agnostic by design, so its tests shouldn't depend on either
  SDK's request/response shape.

No real API call anywhere in this file — `make alts-extract`/`alts-eval`
are the only things that spend real money, deliberately outside CI.
"""

import types
from decimal import Decimal
from unittest.mock import MagicMock

from parvum_alts_hitl.book import build_fund_book
from parvum_alts_hitl.extract import (
    _TOOLS_BY_DOC_TYPE,
    AnthropicProvider,
    LLMProvider,
    OpenRouterProvider,
    build_provider,
    extract_document,
    pdf_text,
    self_consistency_ok,
)
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


class FakeProvider(LLMProvider):
    """A minimal LLMProvider stand-in for testing extract_document() without
    depending on either real SDK's request/response shape."""

    def __init__(self, fields: dict, model: str = "fake-model"):
        self.model = model
        self._fields = fields
        self.last_call = None

    def extract(self, tool: dict, document_text: str) -> dict:
        self.last_call = (tool, document_text)
        return dict(self._fields)


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


def test_every_tool_schema_requires_currency() -> None:
    # D-061: the corpus now spans USD and EUR funds, so the model has to
    # report which one it's reading rather than one being assumed.
    for doc_type, tool in _TOOLS_BY_DOC_TYPE.items():
        assert "currency" in tool["input_schema"]["properties"], doc_type
        assert "currency" in tool["input_schema"]["required"], doc_type


def test_call_missing_an_amount_is_not_self_consistent() -> None:
    fields = {
        "call_amount": None,
        "cumulative_called": "100.00",
        "remaining_commitment": "900.00",
    }
    assert self_consistency_ok("capital_call", fields) is False


class TestExtractDocumentWithAFakeProvider:
    def test_keeps_self_reported_confidence_when_consistent(self) -> None:
        call = build_fund_book(COMMITMENT).calls[0]
        provider = FakeProvider(
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

        result = extract_document(provider, render_capital_call(call), "capital_call")

        assert result.self_reported_confidence == 0.95
        assert result.self_consistent is True
        assert result.confidence == 0.95
        assert result.model == "fake-model"
        assert "confidence" not in result.fields

    def test_caps_confidence_when_inconsistent(self) -> None:
        call = build_fund_book(COMMITMENT).calls[0]
        provider = FakeProvider(
            {
                "fund_name": call.fund_name,
                "account_id": call.account_id,
                "call_number": call.call_number,
                "call_date": call.call_date.isoformat(),
                "due_date": call.due_date.isoformat(),
                "call_amount": None,
                "cumulative_called": str(call.cumulative_called),
                "remaining_commitment": str(call.remaining_commitment),
                "purpose": call.purpose,
                "confidence": 0.9,
            }
        )

        result = extract_document(provider, render_capital_call(call), "capital_call")

        assert result.self_consistent is False
        assert result.confidence == 0.5

    def test_passes_the_right_tool_to_the_provider(self) -> None:
        call = build_fund_book(COMMITMENT).calls[0]
        provider = FakeProvider({"confidence": 0.5})

        extract_document(provider, render_capital_call(call), "capital_call")

        tool, text = provider.last_call
        assert tool["name"] == "extract_capital_call"
        assert call.fund_name in text


class TestAnthropicProvider:
    def test_calls_the_anthropic_sdk_with_a_forced_tool_choice(self) -> None:
        provider = AnthropicProvider(model="claude-haiku-4-5-20251001", api_key="test-key")
        provider._client = MagicMock()
        block = types.SimpleNamespace(type="tool_use", input={"confidence": 0.9})
        provider._client.messages.create.return_value = types.SimpleNamespace(content=[block])

        result = provider.extract({"name": "extract_capital_call"}, "some document text")

        assert result == {"confidence": 0.9}
        _, kwargs = provider._client.messages.create.call_args
        assert kwargs["tool_choice"] == {"type": "tool", "name": "extract_capital_call"}
        assert kwargs["model"] == "claude-haiku-4-5-20251001"


class TestOpenRouterProvider:
    def test_translates_the_tool_schema_to_openai_function_calling_shape(self) -> None:
        provider = OpenRouterProvider(model="anthropic/claude-haiku-4.5", api_key="test-key")
        provider._client = MagicMock()
        call = types.SimpleNamespace(
            function=types.SimpleNamespace(arguments='{"confidence": 0.8}')
        )
        message = types.SimpleNamespace(tool_calls=[call])
        provider._client.chat.completions.create.return_value = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

        tool = {
            "name": "extract_capital_call",
            "description": "Extract a capital call.",
            "input_schema": {"type": "object", "properties": {}},
        }
        result = provider.extract(tool, "some document text")

        assert result == {"confidence": 0.8}
        _, kwargs = provider._client.chat.completions.create.call_args
        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "extract_capital_call"},
        }
        assert kwargs["tools"][0]["function"]["parameters"] == tool["input_schema"]
        assert kwargs["model"] == "anthropic/claude-haiku-4.5"


class TestBuildProvider:
    def test_defaults_to_the_providers_default_model(self) -> None:
        provider = build_provider("anthropic")
        assert provider.model == "claude-haiku-4-5-20251001"

    def test_honors_an_explicit_model_override(self) -> None:
        provider = build_provider("anthropic", model="claude-sonnet-5")
        assert provider.model == "claude-sonnet-5"

    def test_openrouter_defaults_to_a_claude_model_too(self) -> None:
        provider = build_provider("openrouter")
        assert isinstance(provider, OpenRouterProvider)
        assert "claude" in provider.model

    def test_rejects_an_unknown_provider_name(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="unknown LLM provider"):
            build_provider("not-a-real-provider")
