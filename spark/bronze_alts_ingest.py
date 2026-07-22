# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze alts ingest — document, extraction, and review-decision registries
# MAGIC
# MAGIC Walks the alts landing volume and registers three things: every
# MAGIC private-fund PDF (`bronze_alts_documents`), every landed extraction
# MAGIC result (`bronze_alts_extractions`, D-049's structured-field JSON from
# MAGIC Claude), and every landed human review decision (`bronze_alts_review_decisions`,
# MAGIC D-054's reverse-sync — a queue item a reviewer approved or corrected in
# MAGIC the internal app, landed the same way the PDFs are, just going the other
# MAGIC direction). All three are registration only — no deterministic parser
# MAGIC exists for a PDF, and both JSON payloads are already structured by the
# MAGIC time they land, nothing left to parse. This notebook's whole job is:
# MAGIC what do we have, and where.
# MAGIC
# MAGIC Same restatement discipline as `bronze_ingest.py` for both: path
# MAGIC *and* sha256, not path alone, so a re-landed file is detected as
# MAGIC changed rather than silently skipped.

# COMMAND ----------

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# This notebook lives at <repo>/spark/; the alts-hitl package at
# <repo>/alts-hitl/src — same Git-folder-relative-path trick bronze_ingest.py
# uses for parvum_ingest, so the document-type-from-filename mapping is
# taught once (generate.py's own naming convention) and shared, not copied.
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "alts-hitl", "src")))

from parvum_alts_hitl.naming import doc_type_for as _doc_type_for

SCHEMA = "workspace.parvum"
LANDING_ROOT = Path("/Volumes/workspace/parvum/landing/alts")


def doc_type_for(file_name: str) -> str:
    return _doc_type_for(file_name) or "UNKNOWN"


# COMMAND ----------

# MAGIC %md ## Tables (created once; no-op afterwards)

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_alts_documents (
    file_path   STRING,
    file_name   STRING,
    fund_id     STRING,
    doc_type    STRING,
    size_bytes  BIGINT,
    sha256      STRING,
    status      STRING,
    ingested_at TIMESTAMP
) COMMENT 'One row per landed alts document — what private-fund PDFs we have, and where'""")  # noqa: F821

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_alts_extractions (
    file_path                STRING,
    source_pdf                STRING,
    fund_id                   STRING,
    document                  STRING,
    doc_type                  STRING,
    model                     STRING,
    prompt_version            STRING,
    fields_json               STRING,
    self_reported_confidence  DOUBLE,
    self_consistent           BOOLEAN,
    confidence                DOUBLE,
    sha256                    STRING,
    ingested_at               TIMESTAMP
) COMMENT 'One row per landed LLM extraction result (D-049) — fields_json is the raw extracted-field object; schema varies by doc_type, so it is kept as JSON text rather than forced into a fixed wide table.'""")  # noqa: F821

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_alts_review_decisions (
    file_path         STRING,
    fund_id           STRING,
    document          STRING,
    doc_type          STRING,
    sequence_number   INT,
    period_end        STRING,
    status            STRING,
    final_fields_json STRING,
    decided_at        TIMESTAMP,
    sha256            STRING,
    ingested_at       TIMESTAMP
) COMMENT 'One row per landed human review decision (the D-054 reverse-sync) — a queue item a reviewer approved or corrected in the internal app. final_fields_json is the reviewer-confirmed field values (identical to the extraction for an approve, the reviewer own values for a correct).'""")  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)

# COMMAND ----------

COLUMN_COMMENTS = {
    "bronze_alts_documents": {
        "file_path": "Full volume path — the lineage key an extraction row points back to",
        "file_name": "Base name of the landed PDF",
        "fund_id": "Fund identifier, from the <fund_id>/ directory the file landed in",
        "doc_type": "capital_call | distribution | capital_account_statement | UNKNOWN",
        "size_bytes": "File size on arrival",
        "sha256": "Content digest — how a re-landed document is detected as changed",
        "status": "LANDED — the only value this notebook produces; extraction/validation "
        "status lives in later tables, not here",
        "ingested_at": "When this file was registered into bronze (UTC)",
    },
    "bronze_alts_extractions": {
        "file_path": "Full volume path of the landed *.extracted.json file",
        "source_pdf": "Document file name this extraction was read from (bronze_alts_documents.file_name)",
        "fund_id": "Fund identifier, from the <fund_id>/ directory the file landed in",
        "document": "Source PDF's file name (parvum_alts_hitl.extract's own record field)",
        "doc_type": "capital_call | distribution | capital_account_statement",
        "model": "Claude model id used for this extraction",
        "prompt_version": "extract.py's PROMPT_VERSION at the time of extraction",
        "fields_json": "The extracted fields, as raw JSON text (shape varies by doc_type)",
        "self_reported_confidence": "The model's own stated confidence (0.0-1.0), before the self-consistency cap",
        "self_consistent": "Whether extract.py's single-document arithmetic/presence check passed",
        "confidence": "Hybrid confidence actually used downstream (self-reported, capped at 0.5 if not self-consistent)",
        "sha256": "Content digest of the extraction JSON — how a re-landed extraction is detected as changed",
        "ingested_at": "When this file was registered into bronze (UTC)",
    },
    "bronze_alts_review_decisions": {
        "file_path": "Full volume path of the landed *.decision.json file",
        "fund_id": "Fund identifier, from the <fund_id>/ directory the file landed in",
        "document": "Source PDF's file name — the same key bronze_alts_extractions.document uses",
        "doc_type": "capital_call | distribution | capital_account_statement",
        "sequence_number": "call_number or distribution_number carried from the review queue; NULL for capital_account_statement",
        "period_end": "Statement period end (ISO date, as decided); NULL for calls/distributions",
        "status": "approved | corrected — the review decision recorded in the internal app",
        "final_fields_json": "The reviewer-confirmed field values, as raw JSON text (identical to the extraction for an approve, the reviewer's own values for a correct)",
        "decided_at": "When the reviewer made this decision, in the internal app (UTC)",
        "sha256": "Content digest of the decision JSON — how a re-landed decision is detected as changed",
        "ingested_at": "When this file was registered into bronze (UTC)",
    },
}


def sync_column_comments(table: str, comments: dict[str, str]) -> None:
    """Apply column comments unless already present (sentinel: first column)."""
    sentinel_col, sentinel_comment = next(iter(comments.items()))
    described = spark.sql(f"DESCRIBE TABLE {SCHEMA}.{table}").collect()  # noqa: F821
    current = {r["col_name"]: r["comment"] for r in described}
    if current.get(sentinel_col) == sentinel_comment:
        return
    for col, comment in comments.items():
        escaped = comment.replace("'", "''")
        spark.sql(f"ALTER TABLE {SCHEMA}.{table} ALTER COLUMN {col} COMMENT '{escaped}'")  # noqa: F821
    print(f"column comments applied: {table}")


for _table, _comments in COLUMN_COMMENTS.items():
    sync_column_comments(_table, _comments)

# COMMAND ----------

# MAGIC %md ## Shared discovery: new files, and restatements
# MAGIC
# MAGIC Same shape for both tables — path known? sha256 changed? — so it's
# MAGIC written once and applied to each landing subdirectory in turn.

# COMMAND ----------


def discover(root: Path, glob_pattern: str, table: str) -> tuple[list, list, int]:
    registry_sha = {
        r.file_path: r.sha256
        for r in spark.table(f"{SCHEMA}.{table}").select("file_path", "sha256").collect()  # noqa: F821
    }
    new_files, restated_files, unchanged = [], [], 0
    if not root.exists():
        return new_files, restated_files, unchanged
    for fund_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(fund_dir.glob(glob_pattern)):
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            known = registry_sha.get(str(f))
            if known is None:
                new_files.append((f, digest))
            elif known != digest:
                restated_files.append((f, digest))
            else:
                unchanged += 1
    return new_files, restated_files, unchanged


def supersede(table: str, restated_files: list) -> None:
    if not restated_files:
        return
    spark.createDataFrame(  # noqa: F821
        [(str(f),) for f, _ in restated_files], "file_path STRING"
    ).createOrReplaceTempView("restated_paths")
    spark.sql(f"DELETE FROM {SCHEMA}.{table} WHERE file_path IN (SELECT file_path FROM restated_paths)")  # noqa: F821
    print(f"{table}: superseded {len(restated_files)} restated files")


def register(table: str, rows: list[dict]) -> None:
    if rows:
        target = spark.table(f"{SCHEMA}.{table}")  # noqa: F821
        df = spark.createDataFrame(rows, schema=target.schema)  # noqa: F821
        df.write.mode("append").saveAsTable(f"{SCHEMA}.{table}")
    print(f"{table}: registered {len(rows)} rows")


# COMMAND ----------

# MAGIC %md ## Documents

# COMMAND ----------

doc_new, doc_restated, doc_unchanged = discover(
    LANDING_ROOT / "raw", "*.pdf", "bronze_alts_documents"
)
print(f"documents: {doc_unchanged} unchanged; {len(doc_new)} new; {len(doc_restated)} restated")
supersede("bronze_alts_documents", doc_restated)

run_ts = datetime.now(timezone.utc)
doc_rows = [
    {
        "file_path": str(f),
        "file_name": f.name,
        "fund_id": f.parent.name,
        "doc_type": doc_type_for(f.name),
        "size_bytes": f.stat().st_size,
        "sha256": digest,
        "status": "LANDED",
        "ingested_at": run_ts,
    }
    for f, digest in doc_new + doc_restated
]
register("bronze_alts_documents", doc_rows)

# COMMAND ----------

# MAGIC %md ## Extractions

# COMMAND ----------

ext_new, ext_restated, ext_unchanged = discover(
    LANDING_ROOT / "extracted", "*.extracted.json", "bronze_alts_extractions"
)
print(f"extractions: {ext_unchanged} unchanged; {len(ext_new)} new; {len(ext_restated)} restated")
supersede("bronze_alts_extractions", ext_restated)

ext_rows = []
for f, digest in ext_new + ext_restated:
    record = json.loads(f.read_text(encoding="utf-8"))
    ext_rows.append(
        {
            "file_path": str(f),
            "source_pdf": record["document"],
            "fund_id": f.parent.name,
            "document": record["document"],
            "doc_type": record["doc_type"],
            "model": record["model"],
            "prompt_version": record["prompt_version"],
            "fields_json": json.dumps(record["fields"]),
            "self_reported_confidence": record["self_reported_confidence"],
            "self_consistent": record["self_consistent"],
            "confidence": record["confidence"],
            "sha256": digest,
            "ingested_at": run_ts,
        }
    )
register("bronze_alts_extractions", ext_rows)

# COMMAND ----------

# MAGIC %md ## Review decisions

# COMMAND ----------

dec_new, dec_restated, dec_unchanged = discover(
    LANDING_ROOT / "reviewed", "*.decision.json", "bronze_alts_review_decisions"
)
print(f"review decisions: {dec_unchanged} unchanged; {len(dec_new)} new; {len(dec_restated)} restated")
supersede("bronze_alts_review_decisions", dec_restated)

dec_rows = []
for f, digest in dec_new + dec_restated:
    record = json.loads(f.read_text(encoding="utf-8"))
    dec_rows.append(
        {
            "file_path": str(f),
            "fund_id": record["fund_id"],
            "document": record["document"],
            "doc_type": record["doc_type"],
            "sequence_number": record["sequence_number"],
            "period_end": record["period_end"],
            "status": record["status"],
            "final_fields_json": json.dumps(record["final_fields"]),
            "decided_at": datetime.fromisoformat(record["decided_at"]),
            "sha256": digest,
            "ingested_at": run_ts,
        }
    )
register("bronze_alts_review_decisions", dec_rows)

# COMMAND ----------

# MAGIC %md ## What do we have?

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT fund_id, doc_type, COUNT(*) AS documents
        FROM {SCHEMA}.bronze_alts_documents
        GROUP BY fund_id, doc_type ORDER BY fund_id, doc_type"""
    )
)
display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT fund_id, doc_type, COUNT(*) AS extractions, ROUND(AVG(confidence), 2) AS avg_confidence
        FROM {SCHEMA}.bronze_alts_extractions
        GROUP BY fund_id, doc_type ORDER BY fund_id, doc_type"""
    )
)
display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT fund_id, doc_type, status, COUNT(*) AS decisions
        FROM {SCHEMA}.bronze_alts_review_decisions
        GROUP BY fund_id, doc_type, status ORDER BY fund_id, doc_type, status"""
    )
)
