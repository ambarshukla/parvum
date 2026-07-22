"""Mirrors the review queue's source PDFs into Postgres.

Digest-gated: a document whose sha256 already matches what's stored is left
alone and never downloaded, so a reload costs one SQL query and nothing
else. ``download`` is injected rather than imported so the whole decision
table (skip / fetch / replace) is testable without touching the network.
"""

from collections.abc import Callable

from psycopg import Connection, sql

from parvum_export.alts_document_source import DocumentRef

_UPSERT = """
    INSERT INTO {table} (fund_id, document, content, byte_size, sha256)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (fund_id, document) DO UPDATE SET
        content   = EXCLUDED.content,
        byte_size = EXCLUDED.byte_size,
        sha256    = EXCLUDED.sha256,
        loaded_at = now()
"""


def load_documents(
    connection: Connection,
    schema: str,
    index: tuple[DocumentRef, ...],
    download: Callable[[str], bytes],
) -> dict[str, int]:
    """Store any document whose bytes we don't already hold.

    Returns a small summary for the caller to print: how many documents the
    queue references, and how many actually had to be fetched.
    """
    table = sql.Identifier(schema, "alts_documents")

    stored = {
        (fund_id, document): sha
        for fund_id, document, sha in connection.execute(
            sql.SQL("SELECT fund_id, document, sha256 FROM {table}").format(table=table)
        ).fetchall()
    }

    fetched = 0
    with connection.transaction():
        for ref in index:
            if stored.get((ref.fund_id, ref.document)) == ref.sha256:
                continue
            content = download(ref.volume_path)
            connection.execute(
                sql.SQL(_UPSERT).format(table=table),
                (ref.fund_id, ref.document, content, len(content), ref.sha256),
            )
            fetched += 1

    return {"documents": len(index), "fetched": fetched}
