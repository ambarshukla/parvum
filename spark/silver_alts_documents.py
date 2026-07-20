# Databricks notebook source
# MAGIC %md
# MAGIC # Silver alts documents — cross-document validation and routing
# MAGIC
# MAGIC `extract.py` (D-049) already checks each document *against itself*
# MAGIC (does its own arithmetic add up, are required fields present) — that
# MAGIC check runs at extraction time and rides along as
# MAGIC `bronze_alts_extractions.self_consistent`. What it structurally
# MAGIC cannot check is anything that needs a *whole fund's* documents
# MAGIC together: does the cumulative-called figure on call #3 actually equal
# MAGIC the sum of calls #1–#3, is the call sequence gap-free, does one
# MAGIC statement's beginning balance match the prior statement's ending
# MAGIC balance. That's `parvum_alts_hitl.validate`'s whole job — this
# MAGIC notebook is orchestration only, the same "notebook imports a tested
# MAGIC package function" pattern `bronze_ingest.py` already established.
# MAGIC
# MAGIC Full rebuild, like every other silver table in this project: a pure
# MAGIC function of bronze, restatement-proof by construction.
# MAGIC
# MAGIC **Output is a routing decision, not a correction.** This notebook
# MAGIC never edits an extracted value — it only flags whether the extracted
# MAGIC values reconcile, and routes the document to `auto_accept` or
# MAGIC `needs_review` accordingly. Fixing a flagged document is a human's
# MAGIC job (the review queue, a later slice), not this one's.

# COMMAND ----------

import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "alts-hitl", "src")))

from parvum_alts_hitl.validate import validate_fund_documents

SCHEMA = "workspace.parvum"

# COMMAND ----------

# MAGIC %md ## Table (created once; no-op afterwards)

# COMMAND ----------

spark.sql(f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_alts_documents (
    fund_id               STRING,
    document              STRING,
    doc_type              STRING,
    sequence_number        INT,
    period_end             STRING,
    confidence              DOUBLE,
    self_consistent         BOOLEAN,
    cross_document_valid    BOOLEAN,
    validation_notes        STRING,
    routing                 STRING
) COMMENT 'One row per extracted alts document: cross-document validation (parvum_alts_hitl.validate, on top of D-049s extraction self-check) and the resulting auto_accept vs needs_review routing decision.'""")  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)

# COMMAND ----------

COLUMN_COMMENTS = {
    "silver_alts_documents": {
        "fund_id": "Fund identifier",
        "document": "Source PDF file name",
        "doc_type": "capital_call | distribution | capital_account_statement",
        "sequence_number": "call_number or distribution_number; NULL for capital_account_statement",
        "period_end": "Statement period end (ISO date, as extracted); NULL for calls/distributions",
        "confidence": "Hybrid confidence carried from bronze_alts_extractions",
        "self_consistent": "Single-document self-check result, carried from bronze_alts_extractions",
        "cross_document_valid": "Whether this document reconciles against the rest of its fund's documents (see validation_notes)",
        "validation_notes": "Human-readable explanation when cross_document_valid is false; NULL when true",
        "routing": "auto_accept | needs_review",
    },
}


def sync_column_comments(table: str, comments: dict[str, str]) -> None:
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

# MAGIC %md ## Load extractions (small data — driver-side, like bronze_ingest.py)

# COMMAND ----------

extractions = spark.table(f"{SCHEMA}.bronze_alts_extractions").collect()  # noqa: F821

by_fund: dict[str, list[dict]] = {}
for row in extractions:
    by_fund.setdefault(row.fund_id, []).append(
        {
            "document": row.document,
            "doc_type": row.doc_type,
            "confidence": row.confidence,
            "self_consistent": row.self_consistent,
            "fields": json.loads(row.fields_json),
        }
    )

print(f"{len(extractions)} extractions across {len(by_fund)} funds")

# COMMAND ----------

# MAGIC %md ## Validate and route, per fund

# COMMAND ----------

rows = []
for fund_id, docs in by_fund.items():
    for doc in validate_fund_documents(docs):
        rows.append(
            {
                "fund_id": fund_id,
                "document": doc["document"],
                "doc_type": doc["doc_type"],
                "sequence_number": doc["sequence_number"],
                "period_end": doc["period_end"],
                "confidence": doc["confidence"],
                "self_consistent": doc["self_consistent"],
                "cross_document_valid": doc["cross_document_valid"],
                "validation_notes": doc["validation_notes"],
                "routing": doc["routing"],
            }
        )

if rows:
    target = spark.table(f"{SCHEMA}.silver_alts_documents")  # noqa: F821
    df = spark.createDataFrame(rows, schema=target.schema)  # noqa: F821
    df.write.mode("overwrite").saveAsTable(f"{SCHEMA}.silver_alts_documents")

print(f"validated {len(rows)} documents")

# COMMAND ----------

# MAGIC %md ## Routing summary

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT fund_id, doc_type, routing, COUNT(*) AS documents
        FROM {SCHEMA}.silver_alts_documents
        GROUP BY fund_id, doc_type, routing ORDER BY fund_id, doc_type, routing"""
    )
)
