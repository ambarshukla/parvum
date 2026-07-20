"""LLM extraction of alts documents via Claude — runs outside Databricks
(Free Edition can't reach the open internet), the same fetch/process split
that governs every external call in this platform (see
``docs/ARCHITECTURE.md``).

Each document type gets a forced tool-use call, so the response is
guaranteed to match a JSON schema rather than being free-text prose to
parse. Confidence is hybrid: the model's own self-reported read confidence,
folded together with a deterministic single-document self-consistency check
(does what was extracted even add up) — a later slice adds the
cross-document checks (commitment continuity, call sequencing) that need a
whole fund's documents together, not just one PDF, and naturally belong in
the Databricks silver job, not here.
"""

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

import anthropic
from pypdf import PdfReader

from parvum_alts_hitl.naming import doc_type_for

MODEL = "claude-haiku-4-5-20251001"
PROMPT_VERSION = "alts-extract-v1"

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


def extract_document(
    client: anthropic.Anthropic, pdf_bytes: bytes, doc_type: str
) -> ExtractionResult:
    tool = _TOOLS_BY_DOC_TYPE[doc_type]
    text = pdf_text(pdf_bytes)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": f"Document text:\n\n{text}"}],
    )

    tool_use = next(block for block in response.content if block.type == "tool_use")
    raw_fields = dict(tool_use.input)
    self_reported = float(raw_fields.pop("confidence"))
    consistent = self_consistency_ok(doc_type, raw_fields)
    # Hybrid: the model's own confidence, capped if its own numbers don't
    # even add up internally — a floor a self-reported score alone can't
    # provide, since the model has no independent way to "know" it's wrong.
    hybrid = self_reported if consistent else min(self_reported, 0.5)

    return ExtractionResult(
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        fields=raw_fields,
        self_reported_confidence=self_reported,
        self_consistent=consistent,
        confidence=hybrid,
    )


def process_directory(raw_dir: Path, out_dir: Path) -> list[dict]:
    client = anthropic.Anthropic()
    records = []
    for fund_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        fund_out = out_dir / fund_dir.name
        fund_out.mkdir(parents=True, exist_ok=True)
        for pdf_path in sorted(fund_dir.glob("*.pdf")):
            doc_type = doc_type_for(pdf_path.name)
            if doc_type is None:
                continue
            result = extract_document(client, pdf_path.read_bytes(), doc_type)
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
        description="Extract structured fields from alts documents via Claude."
    )
    parser.add_argument("--raw", type=Path, default=Path("../data/alts/raw"))
    parser.add_argument("--out", type=Path, default=Path("../data/alts/extracted"))
    args = parser.parse_args()

    records = process_directory(args.raw, args.out)
    print(f"extracted {len(records)} documents -> {args.out}")


if __name__ == "__main__":
    main()
