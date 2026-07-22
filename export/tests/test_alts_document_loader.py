"""Digest-gated PDF mirroring, against a real Postgres migrated with the real
migration_internal DDL.

What a green run proves: bytes round-trip through `bytea` unchanged, a
document already stored at the same digest is never re-downloaded, a changed
digest replaces the stored bytes, and the whole thing is keyed per fund (two
funds can hold a document of the same name without colliding).
"""

from parvum_export.alts_document_loader import load_documents
from parvum_export.alts_document_source import DocumentRef

PDF = b"%PDF-1.4\nfirst\n%%EOF\n"
PDF_V2 = b"%PDF-1.4\nsecond, longer\n%%EOF\n"


def ref(fund_id: str, document: str, sha: str) -> DocumentRef:
    return DocumentRef(
        fund_id=fund_id,
        document=document,
        volume_path=f"/Volumes/workspace/parvum/landing/alts/raw/{fund_id}/{document}",
        sha256=sha,
    )


class Downloader:
    """Records every path it was asked for, so a test can assert on what was
    *not* fetched — the whole point of the digest gate."""

    def __init__(self, content: bytes = PDF):
        self.content = content
        self.calls: list[str] = []

    def __call__(self, path: str) -> bytes:
        self.calls.append(path)
        return self.content


def stored(connection, schema, fund_id, document):
    return connection.execute(
        f'SELECT content, byte_size, sha256 FROM "{schema}".alts_documents '
        "WHERE fund_id = %s AND document = %s",
        (fund_id, document),
    ).fetchone()


def test_a_new_document_is_downloaded_and_stored(connection, internal_schema):
    download = Downloader()
    summary = load_documents(
        connection, internal_schema, (ref("FUND-PE01", "call_01.pdf", "aaa"),), download
    )

    assert summary == {"documents": 1, "fetched": 1}
    assert stored(connection, internal_schema, "FUND-PE01", "call_01.pdf") == (
        PDF,
        len(PDF),
        "aaa",
    )


def test_an_unchanged_digest_is_not_downloaded_again(connection, internal_schema):
    index = (ref("FUND-PE01", "call_01.pdf", "aaa"),)
    load_documents(connection, internal_schema, index, Downloader())

    second = Downloader()
    summary = load_documents(connection, internal_schema, index, second)

    assert summary == {"documents": 1, "fetched": 0}
    assert second.calls == []


def test_a_changed_digest_replaces_the_stored_bytes(connection, internal_schema):
    load_documents(
        connection, internal_schema, (ref("FUND-PE01", "call_01.pdf", "aaa"),), Downloader(PDF)
    )
    # The document was re-landed upstream: same path, new content, new digest.
    summary = load_documents(
        connection, internal_schema, (ref("FUND-PE01", "call_01.pdf", "bbb"),), Downloader(PDF_V2)
    )

    assert summary == {"documents": 1, "fetched": 1}
    assert stored(connection, internal_schema, "FUND-PE01", "call_01.pdf") == (
        PDF_V2,
        len(PDF_V2),
        "bbb",
    )


def test_the_same_document_name_in_two_funds_does_not_collide(connection, internal_schema):
    download = Downloader()
    summary = load_documents(
        connection,
        internal_schema,
        (ref("FUND-PE01", "call_01.pdf", "aaa"), ref("FUND-VC01", "call_01.pdf", "bbb")),
        download,
    )

    assert summary == {"documents": 2, "fetched": 2}
    assert stored(connection, internal_schema, "FUND-PE01", "call_01.pdf")[2] == "aaa"
    assert stored(connection, internal_schema, "FUND-VC01", "call_01.pdf")[2] == "bbb"
