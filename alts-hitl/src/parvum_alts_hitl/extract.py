"""LLM extraction of alts documents — runs outside Databricks (Free Edition
can't reach the open internet), the same fetch/process split that governs
every external call in this platform (see ``docs/ARCHITECTURE.md``).

Two providers, one interface (D-052). Anthropic direct gives access to the
full Claude lineup — useful for escalating a genuinely hard document to a
bigger model. OpenRouter is a single account/API key in front of many
providers' models (including Claude, routed the same way), a different
billing processor from Anthropic's own Console, and a practical way to keep
extraction running if one vendor's billing has a problem, without changing
anything past this module. Everything downstream of ``provider.extract()``
— the schema, the self-consistency check, the confidence logic — is
provider-agnostic.

Each document type gets a forced tool-use call, so the response is
guaranteed to match a JSON schema rather than being free-text prose to
parse. Confidence is hybrid: the model's own self-reported read confidence,
folded together with a deterministic single-document self-consistency check
(does what was extracted even add up) — a later slice adds the
cross-document checks (commitment continuity, call sequencing) that need a
whole fund's documents together, not just one PDF (see ``validate.py``).
"""

import argparse
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

import anthropic
import openai
from pypdf import PdfReader

from parvum_alts_hitl.naming import doc_type_for

PROMPT_VERSION = "alts-extract-v1"

# Per-provider defaults. Both point at a Claude Haiku-class model today —
# structured extraction from a one-page document with a forced schema
# doesn't need a bigger model's reasoning depth — but OpenRouter's model
# string can be swapped independently (a different provider entirely, not
# just a different Claude size) without touching either provider class.
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openrouter": "anthropic/claude-haiku-4.5",
}

_SYSTEM_PROMPT = (
    "You extract structured data from private-fund (alts) documents for a wealth "
    "management data platform. Read the document text exactly as written — do not "
    "correct, round, or infer values that are not present. If a field is not stated "
    "in the document, use null. Report your own confidence honestly: lower it if the "
    "document's wording, formatting, or numbers look ambiguous, inconsistent, or "
    "unusual."
)

_CALL_TOOL = {
    "name": "extract_capital_call",
    "description": "Extract structured fields from a capital call notice.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fund_name": {"type": "string"},
            "account_id": {"type": "string"},
            "call_number": {"type": "integer"},
            "call_date": {"type": "string", "description": "ISO 8601 YYYY-MM-DD"},
            "due_date": {"type": "string", "description": "ISO 8601 YYYY-MM-DD"},
            "call_amount": {
                "type": "string",
                "description": (
                    "Decimal, no currency symbol or thousands separators, e.g. 150000.00"
                ),
            },
            "cumulative_called": {"type": "string"},
            "remaining_commitment": {"type": "string"},
            "purpose": {"type": ["string", "null"]},
            "confidence": {
                "type": "number",
                "description": "0.0-1.0 confidence every field above was read correctly",
            },
        },
        "required": [
            "fund_name",
            "account_id",
            "call_number",
            "call_date",
            "due_date",
            "call_amount",
            "cumulative_called",
            "remaining_commitment",
            "purpose",
            "confidence",
        ],
    },
}

_DISTRIBUTION_TOOL = {
    "name": "extract_distribution",
    "description": "Extract structured fields from a distribution notice.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fund_name": {"type": "string"},
            "account_id": {"type": "string"},
            "distribution_number": {"type": "integer"},
            "distribution_date": {"type": "string", "description": "ISO 8601 YYYY-MM-DD"},
            "distribution_amount": {"type": "string"},
            "cumulative_distributed": {"type": "string"},
            "source": {
                "type": ["string", "null"],
                "description": "RETURN_OF_CAPITAL | CAPITAL_GAIN | INCOME | null",
            },
            "recallable": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": [
            "fund_name",
            "account_id",
            "distribution_number",
            "distribution_date",
            "distribution_amount",
            "cumulative_distributed",
            "source",
            "recallable",
            "confidence",
        ],
    },
}

_STATEMENT_TOOL = {
    "name": "extract_capital_account_statement",
    "description": "Extract structured fields from a capital account statement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fund_name": {"type": "string"},
            "account_id": {"type": "string"},
            "period_end": {"type": "string", "description": "ISO 8601 YYYY-MM-DD"},
            "beginning_balance": {"type": "string"},
            "contributions": {"type": "string"},
            "distributions": {"type": "string"},
            "management_fees": {"type": "string"},
            "realized_gain_loss": {"type": "string"},
            "unrealized_gain_loss": {"type": "string"},
            "ending_balance": {"type": "string"},
            "total_commitment": {"type": "string"},
            "unfunded_commitment": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": [
            "fund_name",
            "account_id",
            "period_end",
            "beginning_balance",
            "contributions",
            "distributions",
            "management_fees",
            "realized_gain_loss",
            "unrealized_gain_loss",
            "ending_balance",
            "total_commitment",
            "unfunded_commitment",
            "confidence",
        ],
    },
}

_TOOLS_BY_DOC_TYPE = {
    "capital_call": _CALL_TOOL,
    "distribution": _DISTRIBUTION_TOOL,
    "capital_account_statement": _STATEMENT_TOOL,
}


class LLMProvider(ABC):
    """One forced-tool-call extraction, hiding the provider's own request/
    response shape behind a single method — the two providers differ in
    exactly this: how a tool is declared, how the call is forced, and how
    the arguments come back. ``model`` is a plain attribute (not part of
    the method signature) so callers/logging can report which model
    actually produced a given extraction."""

    model: str

    @abstractmethod
    def extract(self, tool: dict, document_text: str) -> dict:
        """Returns the raw extracted-fields dict (still containing the
        ``confidence`` key) from a forced tool call."""


class AnthropicProvider(LLMProvider):
    """Calls Claude directly via Anthropic's native Messages/tool-use API."""

    def __init__(self, model: str, api_key: str | None = None):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def extract(self, tool: dict, document_text: str) -> dict:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": f"Document text:\n\n{document_text}"}],
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return dict(tool_use.input)


class OpenRouterProvider(LLMProvider):
    """Calls a model (Claude or otherwise) through OpenRouter's OpenAI-
    compatible chat-completions API. The tool schema and the response shape
    both need translating from Anthropic's native shape (OpenAI's
    tool-calling uses a different envelope, and returns the arguments as a
    JSON *string* to parse rather than an already-parsed object) —
    everything about the schema's *content*, and everything downstream of
    ``extract()``, stays identical regardless of which provider read the
    document."""

    def __init__(self, model: str, api_key: str | None = None):
        # A placeholder when unset, not None: the openai SDK now validates
        # credential presence at construction time, before any call is
        # attempted — but a missing/wrong key should fail loudly at the
        # real API call (a real auth error), not block building the
        # provider object itself (e.g. for tests that only check wiring).
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY") or "unset"
        self._client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=resolved_key)
        self.model = model

    def extract(self, tool: dict, document_text: str) -> dict:
        function_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        response = self._client.chat.completions.create(
            model=self.model,
            tools=[function_tool],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Document text:\n\n{document_text}"},
            ],
        )
        call = response.choices[0].message.tool_calls[0]
        return json.loads(call.function.arguments)


def build_provider(name: str, model: str | None = None) -> LLMProvider:
    if name not in DEFAULT_MODELS:
        raise ValueError(
            f"unknown LLM provider: {name!r} (expected one of {sorted(DEFAULT_MODELS)})"
        )
    resolved_model = model or DEFAULT_MODELS[name]
    if name == "anthropic":
        return AnthropicProvider(resolved_model)
    return OpenRouterProvider(resolved_model)


def pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def self_consistency_ok(doc_type: str, fields: dict) -> bool:
    """A single-document arithmetic/presence check on the EXTRACTED values —
    independent of ground truth, so it works in production too, not just
    eval."""
    if doc_type == "capital_account_statement":
        parts = (
            "beginning_balance",
            "contributions",
            "distributions",
            "management_fees",
            "realized_gain_loss",
            "unrealized_gain_loss",
            "ending_balance",
        )
        values = {p: _decimal_or_none(fields.get(p)) for p in parts}
        if any(v is None for v in values.values()):
            return False
        expected = (
            values["beginning_balance"]
            + values["contributions"]
            - values["distributions"]
            - values["management_fees"]
            + values["realized_gain_loss"]
            + values["unrealized_gain_loss"]
        )
        return expected == values["ending_balance"]

    if doc_type == "capital_call":
        return all(
            fields.get(f) not in (None, "")
            for f in ("call_amount", "cumulative_called", "remaining_commitment")
        )

    if doc_type == "distribution":
        return all(
            fields.get(f) not in (None, "")
            for f in ("distribution_amount", "cumulative_distributed")
        )

    return False


@dataclass(frozen=True)
class ExtractionResult:
    model: str
    prompt_version: str
    fields: dict
    self_reported_confidence: float
    self_consistent: bool
    confidence: float


def extract_document(provider: LLMProvider, pdf_bytes: bytes, doc_type: str) -> ExtractionResult:
    tool = _TOOLS_BY_DOC_TYPE[doc_type]
    text = pdf_text(pdf_bytes)

    raw_fields = provider.extract(tool, text)
    self_reported = float(raw_fields.pop("confidence"))
    consistent = self_consistency_ok(doc_type, raw_fields)
    # Hybrid: the model's own confidence, capped if its own numbers don't
    # even add up internally — a floor a self-reported score alone can't
    # provide, since the model has no independent way to "know" it's wrong.
    hybrid = self_reported if consistent else min(self_reported, 0.5)

    return ExtractionResult(
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        fields=raw_fields,
        self_reported_confidence=self_reported,
        self_consistent=consistent,
        confidence=hybrid,
    )


def process_directory(raw_dir: Path, out_dir: Path, provider: LLMProvider) -> list[dict]:
    records = []
    for fund_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        fund_out = out_dir / fund_dir.name
        fund_out.mkdir(parents=True, exist_ok=True)
        for pdf_path in sorted(fund_dir.glob("*.pdf")):
            doc_type = doc_type_for(pdf_path.name)
            if doc_type is None:
                continue
            result = extract_document(provider, pdf_path.read_bytes(), doc_type)
            record = {
                "document": pdf_path.name,
                "fund_id": fund_dir.name,
                "doc_type": doc_type,
                "model": result.model,
                "prompt_version": result.prompt_version,
                "fields": result.fields,
                "self_reported_confidence": result.self_reported_confidence,
                "self_consistent": result.self_consistent,
                "confidence": result.confidence,
            }
            (fund_out / f"{pdf_path.stem}.extracted.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8", newline="\n"
            )
            records.append(record)
            print(
                f"{fund_dir.name}/{pdf_path.name}: "
                f"confidence={result.confidence:.2f} self_consistent={result.self_consistent}"
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured fields from alts documents via an LLM."
    )
    parser.add_argument("--raw", type=Path, default=Path("../data/alts/raw"))
    parser.add_argument("--out", type=Path, default=Path("../data/alts/extracted"))
    parser.add_argument(
        "--provider",
        choices=sorted(DEFAULT_MODELS),
        default=os.environ.get("PARVUM_LLM_PROVIDER", "openrouter"),
        help="LLM provider (default: $PARVUM_LLM_PROVIDER or openrouter)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PARVUM_LLM_MODEL"),
        help="override the provider's default model (default: $PARVUM_LLM_MODEL, "
        "else a per-provider default — see DEFAULT_MODELS)",
    )
    args = parser.parse_args()

    provider = build_provider(args.provider, args.model)
    records = process_directory(args.raw, args.out, provider)
    print(f"extracted {len(records)} documents via {args.provider}/{provider.model} -> {args.out}")


if __name__ == "__main__":
    main()
