# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze alts ingest — document registry
# MAGIC
# MAGIC Walks the alts landing volume and records every private-fund
# MAGIC document (capital call, distribution, capital account statement) in
# MAGIC `bronze_alts_documents` — the same "raw as received" discipline as
# MAGIC `bronze_file_registry`, but registration only. Unlike the custodial
# MAGIC feeds there is no deterministic parser for a PDF; content extraction
# MAGIC is a later step, run as an LLM call in GitHub Actions rather than
# MAGIC here (see `docs/ARCHITECTURE.md`'s fetch/process split and D-046/
# MAGIC D-047 in `docs/DECISIONS.md`) — this notebook's whole job is: what
# MAGIC documents do we have, and where.
# MAGIC
# MAGIC Same restatement discipline as `bronze_ingest.py`: path *and* sha256,
# MAGIC not path alone, so a re-landed document is detected as changed
# MAGIC rather than silently skipped.

# COMMAND ----------

import hashlib
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "workspace.parvum"
ALTS_ROOT = Path("/Volumes/workspace/parvum/landing/alts/raw")

# The generator's own filename convention
# (alts-hitl/src/parvum_alts_hitl/generate.py) — inferred from the prefix
# rather than duplicating a doc-type list here, so a new document type only
# has to be taught to the generator, not to this notebook too.
_DOC_TYPE_PREFIXES = {
    "capital_call_": "capital_call",
    "distribution_": "distribution",
    "capital_account_": "capital_account_statement",
}


def doc_type_for(file_name: str) -> str:
    return next(
        (dtype for prefix, dtype in _DOC_TYPE_PREFIXES.items() if file_name.startswith(prefix)),
        "UNKNOWN",
    )


# COMMAND ----------

# MAGIC %md ## Table (created once; no-op afterwards)

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

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)

# COMMAND ----------

COLUMN_COMMENTS = {
    "bronze_alts_documents": {
        "file_path": "Full volume path — the lineage key a later extraction row points back to",
        "file_name": "Base name of the landed PDF",
        "fund_id": "Fund identifier, from the <fund_id>/ directory the file landed in",
        "doc_type": "capital_call | distribution | capital_account_statement | UNKNOWN",
        "size_bytes": "File size on arrival",
        "sha256": "Content digest — how a re-landed document is detected as changed",
        "status": "LANDED — the only value this notebook produces; extraction/validation "
        "status lives in later tables, not here",
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

# MAGIC %md ## Discover work: new documents, and restatements

# COMMAND ----------

registry_sha = {
    r.file_path: r.sha256
    for r in spark.table(f"{SCHEMA}.bronze_alts_documents")  # noqa: F821
    .select("file_path", "sha256")
    .collect()
}

new_files: list[tuple[Path, str]] = []
restated_files: list[tuple[Path, str]] = []
unchanged = 0

for fund_dir in sorted(ALTS_ROOT.iterdir()):
    if not fund_dir.is_dir():
        continue
    for f in sorted(fund_dir.glob("*.pdf")):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        known = registry_sha.get(str(f))
        if known is None:
            new_files.append((f, digest))
        elif known != digest:
            restated_files.append((f, digest))
        else:
            unchanged += 1

print(f"{unchanged} unchanged; {len(new_files)} new; {len(restated_files)} restated")

# COMMAND ----------

# MAGIC %md ## Supersede restated documents
# MAGIC
# MAGIC Delete before re-registering, the same ordering as `bronze_ingest.py`
# MAGIC and for the same reason: if the run dies here, the document looks
# MAGIC un-registered and the next run redoes it cleanly.

# COMMAND ----------

if restated_files:
    spark.createDataFrame(  # noqa: F821
        [(str(f),) for f, _ in restated_files], "file_path STRING"
    ).createOrReplaceTempView("restated_alts_paths")

    spark.sql(  # noqa: F821
        f"DELETE FROM {SCHEMA}.bronze_alts_documents "
        "WHERE file_path IN (SELECT file_path FROM restated_alts_paths)"
    )
    print(f"superseded {len(restated_files)} restated documents")

# COMMAND ----------

# MAGIC %md ## Register

# COMMAND ----------

run_ts = datetime.now(timezone.utc)
rows = [
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
    for f, digest in new_files + restated_files
]

if rows:
    target = spark.table(f"{SCHEMA}.bronze_alts_documents")  # noqa: F821
    df = spark.createDataFrame(rows, schema=target.schema)  # noqa: F821
    df.write.mode("append").saveAsTable(f"{SCHEMA}.bronze_alts_documents")

print(f"registered {len(rows)} documents")

# COMMAND ----------

# MAGIC %md ## What alts documents do we have?

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT fund_id, doc_type, COUNT(*) AS documents
        FROM {SCHEMA}.bronze_alts_documents
        GROUP BY fund_id, doc_type ORDER BY fund_id, doc_type"""
    )
)
