-- The source PDFs behind the review queue, so a reviewer can read the
-- document itself next to the values extracted from it (D-057) instead of
-- taking the extraction on faith.
--
-- Why the bytes live here at all, rather than being streamed from the
-- lakehouse on demand: the serving app has no Databricks credentials and no
-- egress path to the volume, deliberately (D-006 -- everything moves by the
-- exporter pulling, never by serving reaching out). Putting the bytes in
-- Postgres keeps that boundary intact and costs almost nothing: the whole
-- corpus is 32 documents at ~2 KB each, ~128 KB total. If these were real
-- fund documents (megabytes, thousands of them) the right answer would be
-- object storage plus a presigned URL, and this table would become a row of
-- metadata pointing at it.
--
-- A separate table from alts_review_queue, not another column on it, for the
-- same reason bronze splits bronze_alts_documents from
-- bronze_alts_extractions: a PDF is document content with its own lifetime,
-- not review state. Keeping it separate also means the queue's per-run upsert
-- doesn't rewrite a blob on every load.

create table alts_documents (
    fund_id    varchar      not null,
    document   varchar      not null,
    content    bytea        not null,
    byte_size  int          not null,
    sha256     varchar      not null,
    loaded_at  timestamptz  not null default now(),
    primary key (fund_id, document)
);
comment on table alts_documents is
    'Source PDFs for documents in the review queue, mirrored out of the Databricks landing volume by the exporter. Keyed the same way alts_review_queue is (fund_id, document) -- document names are only unique within a fund, never globally.';
comment on column alts_documents.sha256 is
    'Content digest as landed, carried from bronze_alts_documents -- lets a reload skip a document whose bytes have not changed.';
