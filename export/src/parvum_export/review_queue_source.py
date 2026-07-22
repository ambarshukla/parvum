"""Reads needs_review alts documents, joined with their extracted fields,
over the Databricks SQL Statements API.

silver_alts_documents (D-050) carries the routing decision but not the
extracted values themselves — routing is orchestration, not a copy of
bronze. The queue needs both, so this joins back to bronze_alts_extractions
for fields_json. confidence is cast to DECIMAL in the query so the existing
typed-value converter (gold_source.convert_rows) handles it without adding a
DOUBLE case just for this one column.
"""

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from parvum_export.gold_source import ExportError, convert_rows

_QUERY = """
SELECT s.fund_id, s.document, s.doc_type, s.sequence_number, s.period_end,
       b.fields_json, CAST(s.confidence AS DECIMAL(5, 4)), s.validation_notes
FROM workspace.parvum.silver_alts_documents s
JOIN workspace.parvum.bronze_alts_extractions b
  ON b.fund_id = s.fund_id AND b.document = s.document
WHERE s.routing = 'needs_review'
"""


@dataclass(frozen=True)
class ReviewItem:
    fund_id: str
    document: str
    doc_type: str
    sequence_number: int | None
    period_end: date | None
    extracted_fields: dict[str, Any]
    confidence: Decimal
    validation_notes: str | None


def row_to_review_item(row: tuple) -> ReviewItem:
    """Pure — the tested core. row is (fund_id, document, doc_type, sequence_number,
    period_end, fields_json, confidence, validation_notes) already typed by convert_rows,
    except period_end (still an ISO string) and fields_json (still a JSON string)."""
    fund_id, document, doc_type, sequence_number, period_end, fields_json, confidence, notes = row
    return ReviewItem(
        fund_id=fund_id,
        document=document,
        doc_type=doc_type,
        sequence_number=sequence_number,
        period_end=date.fromisoformat(period_end) if period_end is not None else None,
        extracted_fields=json.loads(fields_json),
        confidence=confidence,
        validation_notes=notes,
    )


def fetch_needs_review(host: str, token: str, warehouse_id: str) -> tuple[ReviewItem, ...]:
    body = {"warehouse_id": warehouse_id, "wait_timeout": "50s", "statement": _QUERY}
    request = urllib.request.Request(
        host.rstrip("/") + "/api/2.0/sql/statements",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read())

    state = result.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise ExportError(
            f"needs_review query did not succeed: {json.dumps(result.get('status'))[:300]}"
        )
    manifest = result["manifest"]
    if manifest.get("total_chunk_count", 1) > 1:
        raise ExportError(
            f"needs_review queue no longer fits one inline result chunk "
            f"({manifest.get('total_row_count')} rows) — needs chunked reads now"
        )
    _, rows = convert_rows(
        manifest["schema"]["columns"], result.get("result", {}).get("data_array") or []
    )
    return tuple(row_to_review_item(row) for row in rows)
