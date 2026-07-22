"""Reads the source PDFs behind the review queue out of the Databricks volume.

Two steps, deliberately separate. The *index* is a cheap SQL query naming
every reviewable document and the sha256 of its bytes as landed; the
*download* is one Files API call per document. Splitting them lets the
loader skip downloading anything whose digest it already holds, which is
what makes a reload nearly free rather than re-fetching the whole corpus
every run (D-057).
"""

import json
import urllib.request
from dataclasses import dataclass

from parvum_export.gold_source import ExportError, convert_rows

# Only documents the pipeline actually routed to review -- the queue is the
# only thing that shows a PDF today, so mirroring the other 14 would be bytes
# nobody can reach. The join is on (fund_id, file_name) because document names
# repeat across funds: capital_call_01.pdf exists in both, and matching on the
# name alone would cross the funds over.
_INDEX_QUERY = """
SELECT d.fund_id, d.file_name, d.file_path, d.sha256
FROM workspace.parvum.bronze_alts_documents d
JOIN workspace.parvum.silver_alts_documents s
  ON s.fund_id = d.fund_id AND s.document = d.file_name
WHERE s.routing = 'needs_review'
"""


@dataclass(frozen=True)
class DocumentRef:
    """One reviewable document: where its bytes are, and what they hash to."""

    fund_id: str
    document: str
    volume_path: str
    sha256: str


def fetch_document_index(host: str, token: str, warehouse_id: str) -> tuple[DocumentRef, ...]:
    body = {"warehouse_id": warehouse_id, "wait_timeout": "50s", "statement": _INDEX_QUERY}
    request = urllib.request.Request(
        host.rstrip("/") + "/api/2.0/sql/statements",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read())

    if result.get("status", {}).get("state") != "SUCCEEDED":
        raise ExportError(
            f"document index query did not succeed: {json.dumps(result.get('status'))[:300]}"
        )
    manifest = result["manifest"]
    if manifest.get("total_chunk_count", 1) > 1:
        raise ExportError(
            f"document index no longer fits one inline result chunk "
            f"({manifest.get('total_row_count')} rows) -- needs chunked reads now"
        )
    _, rows = convert_rows(
        manifest["schema"]["columns"], result.get("result", {}).get("data_array") or []
    )
    return tuple(DocumentRef(*row) for row in rows)


def download_document(host: str, token: str, volume_path: str) -> bytes:
    """Fetch one volume file's raw bytes over the Files API.

    Probed against the real volume before this was written: a PDF comes back
    as ``application/octet-stream`` with the ``%PDF`` magic intact, so the
    bytes need no decoding on the way through.
    """
    request = urllib.request.Request(
        host.rstrip("/") + "/api/2.0/fs/files" + volume_path,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    if not content.startswith(b"%PDF"):
        # A truncated or error-page response would otherwise be stored and only
        # surface as an unreadable viewer much later, in the browser.
        raise ExportError(f"{volume_path} did not come back as a PDF ({len(content)} bytes)")
    return content
