# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze ingest — file registry + parsed bronze tables
# MAGIC
# MAGIC Walks the landing volume, records every file in
# MAGIC `bronze_file_registry`, and parses each format into a typed bronze
# MAGIC Delta table using the **same `parvum_ingest` parsers** that
# MAGIC generated the files (the repo is synced here as a Git folder, so
# MAGIC one codebase serves both sides of the wire).
# MAGIC
# MAGIC Principles:
# MAGIC - **Bronze keeps raw-as-received.** The files stay in the volume
# MAGIC   untouched; these tables are the *parsed view*, with `file_path`
# MAGIC   lineage back to every source file.
# MAGIC - **Idempotent.** Files already in the registry are skipped, so
# MAGIC   re-running the notebook never duplicates rows.
# MAGIC - **Failures are data.** A file that cannot be parsed is recorded
# MAGIC   as `FAILED` with its error — not silently dropped, not fatal.
# MAGIC
# MAGIC At this volume (hundreds of small files) parsing runs on the
# MAGIC driver in plain Python — honest and simple. The scale-up path
# MAGIC (distribute parsing with `mapInPandas` over a file list) is a
# MAGIC deliberate later exercise.

# COMMAND ----------

# MAGIC %pip install pydantic>=2.7

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import hashlib
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# This notebook lives at <repo>/spark/; the ingest package at <repo>/ingest/src.
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "ingest", "src")))

from parvum_ingest.formats import FeedParseError
from parvum_ingest.formats.camt053 import parse_camt053
from parvum_ingest.formats.mt535 import parse_mt535
from parvum_ingest.formats.semt002 import parse_semt002

SCHEMA = "workspace.parvum"
RAW_ROOT = Path("/Volumes/workspace/parvum/landing/raw")

# Parser dispatch by filename suffix (set by the generator).
PARSERS = {
    ".semt002.xml": ("semt.002", parse_semt002),
    ".mt535.txt": ("MT535", parse_mt535),
    ".camt053.xml": ("camt.053", parse_camt053),
}

# COMMAND ----------

# MAGIC %md ## Tables (created once; no-ops afterwards)

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_file_registry (
    file_path      STRING  COMMENT 'full volume path — lineage key',
    file_name      STRING,
    format         STRING,
    statement_date DATE    COMMENT 'from the date= directory name',
    size_bytes     BIGINT,
    sha256         STRING,
    status         STRING  COMMENT 'PARSED | FAILED',
    error          STRING,
    ingested_at    TIMESTAMP
) COMMENT 'One row per raw file received — the answer to: what raw data do we have?'""")  # noqa: F821

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_holdings (
    file_path         STRING,
    statement_id      STRING,
    source_format     STRING,
    as_of             DATE,
    account_id        STRING,
    security_scheme   STRING,
    security_id       STRING,
    security_name     STRING,
    quantity          DECIMAL(24,6),
    price_amount      DECIMAL(24,6),
    price_currency    STRING,
    price_as_of       DATE,
    market_value      DECIMAL(24,2),
    market_value_ccy  STRING,
    cost_basis        DECIMAL(24,2),
    cost_basis_ccy    STRING,
    ingested_at       TIMESTAMP
) COMMENT 'Positions as received, one row per position per file. No cleaning here.'""")  # noqa: F821

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_cash_entries (
    file_path       STRING,
    statement_id    STRING,
    as_of           DATE,
    account_id      STRING,
    transaction_id  STRING,
    type            STRING,
    trade_date      DATE,
    settlement_date DATE,
    amount          DECIMAL(24,2),
    currency        STRING,
    description     STRING,
    ingested_at     TIMESTAMP
) COMMENT 'Cash statement entries as received.'""")  # noqa: F821

spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.bronze_cash_balances (
    file_path    STRING,
    statement_id STRING,
    as_of        DATE,
    account_id   STRING,
    balance_type STRING,
    amount       DECIMAL(24,2),
    currency     STRING,
    ingested_at  TIMESTAMP
) COMMENT 'Opening/closing balances as received.'""")  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Discover new files (idempotency = anti-join against the registry)

# COMMAND ----------

already_ingested = {
    r.file_path
    for r in spark.table(f"{SCHEMA}.bronze_file_registry").select("file_path").collect()  # noqa: F821
}

new_files = []
for day_dir in sorted(RAW_ROOT.glob("date=*")):
    for f in sorted(day_dir.iterdir()):
        if str(f) not in already_ingested:
            new_files.append(f)

print(f"{len(already_ingested)} files already ingested; {len(new_files)} new")

# COMMAND ----------

# MAGIC %md ## Parse

# COMMAND ----------

run_ts = datetime.now(timezone.utc)
registry_rows, holdings_rows, entry_rows, balance_rows = [], [], [], []

for f in new_files:
    fmt = next((name for suffix, (name, _) in PARSERS.items() if f.name.endswith(suffix)), None)
    parser = next((p for suffix, (_, p) in PARSERS.items() if f.name.endswith(suffix)), None)
    text = f.read_text(encoding="utf-8")
    stmt_date = date.fromisoformat(f.parent.name.removeprefix("date="))

    base = {
        "file_path": str(f),
        "file_name": f.name,
        "format": fmt or "UNKNOWN",
        "statement_date": stmt_date,
        "size_bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "ingested_at": run_ts,
    }

    if parser is None:
        registry_rows.append({**base, "status": "FAILED", "error": "unrecognised filename"})
        continue

    try:
        stmt = parser(text)
    except FeedParseError as exc:
        # Failures are data: recorded, queryable, never fatal to the run.
        registry_rows.append({**base, "status": "FAILED", "error": str(exc)})
        continue

    registry_rows.append({**base, "status": "PARSED", "error": None})

    if fmt in ("semt.002", "MT535"):
        for p in stmt.positions:
            holdings_rows.append(
                {
                    "file_path": str(f),
                    "statement_id": stmt.statement_id,
                    "source_format": stmt.source_format.value,
                    "as_of": stmt.as_of,
                    "account_id": p.account_id,
                    "security_scheme": p.security.scheme.value,
                    "security_id": p.security.value,
                    "security_name": p.security_name,
                    "quantity": p.quantity,
                    "price_amount": None if p.price is None else p.price.amount,
                    "price_currency": None if p.price is None else p.price.currency,
                    "price_as_of": p.price_as_of,
                    "market_value": None if p.market_value is None else p.market_value.amount,
                    "market_value_ccy": None if p.market_value is None else p.market_value.currency,
                    "cost_basis": None if p.cost_basis is None else p.cost_basis.amount,
                    "cost_basis_ccy": None if p.cost_basis is None else p.cost_basis.currency,
                    "ingested_at": run_ts,
                }
            )
    else:
        for t in stmt.entries:
            entry_rows.append(
                {
                    "file_path": str(f),
                    "statement_id": stmt.statement_id,
                    "as_of": stmt.as_of,
                    "account_id": t.account_id,
                    "transaction_id": t.transaction_id,
                    "type": t.type.value,
                    "trade_date": t.trade_date,
                    "settlement_date": t.settlement_date,
                    "amount": t.amount.amount,
                    "currency": t.amount.currency,
                    "description": t.description,
                    "ingested_at": run_ts,
                }
            )
        for b in stmt.balances:
            balance_rows.append(
                {
                    "file_path": str(f),
                    "statement_id": stmt.statement_id,
                    "as_of": stmt.as_of,
                    "account_id": b.account_id,
                    "balance_type": b.balance_type.value,
                    "amount": b.balance.amount,
                    "currency": b.balance.currency,
                    "ingested_at": run_ts,
                }
            )

print(
    f"parsed: {sum(1 for r in registry_rows if r['status'] == 'PARSED')}, "
    f"failed: {sum(1 for r in registry_rows if r['status'] == 'FAILED')}, "
    f"holdings rows: {len(holdings_rows)}, cash entries: {len(entry_rows)}, "
    f"balances: {len(balance_rows)}"
)

# COMMAND ----------

# MAGIC %md ## Append to Delta (schemas come from the tables themselves)

# COMMAND ----------


def append(table: str, rows: list[dict]) -> None:
    if rows:
        target = spark.table(f"{SCHEMA}.{table}")  # noqa: F821
        df = spark.createDataFrame(rows, schema=target.schema)  # noqa: F821
        df.write.mode("append").saveAsTable(f"{SCHEMA}.{table}")


append("bronze_holdings", holdings_rows)
append("bronze_cash_entries", entry_rows)
append("bronze_cash_balances", balance_rows)
append("bronze_file_registry", registry_rows)  # last: a crash before this line reprocesses cleanly

# COMMAND ----------

# MAGIC %md ## What raw data do we have? (the registry answers)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT format, status, COUNT(*) AS files,
               MIN(statement_date) AS first_day, MAX(statement_date) AS last_day
        FROM {SCHEMA}.bronze_file_registry
        GROUP BY format, status ORDER BY format"""
    )
)
