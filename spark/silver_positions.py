# Databricks notebook source
# MAGIC %md
# MAGIC # Silver — conformed positions, joined to what they mean
# MAGIC
# MAGIC Bronze answers *what did the custodian say*; silver answers *what do
# MAGIC we hold, and whose is it*. This notebook joins `bronze_holdings` to
# MAGIC the two reference layers — the securities master (landed in the
# MAGIC volume, since the workspace has no egress) and the ownership graph
# MAGIC (code, imported from `parvum_reference` in this repo checkout).
# MAGIC
# MAGIC Principles:
# MAGIC - **One grain per table.** `silver_positions` is one row per
# MAGIC   (date, account, security); the owner attribution lives in separate
# MAGIC   tables so summing market value can never double-count a
# MAGIC   shared account.
# MAGIC - **Full rebuild.** Silver is a pure projection of bronze ×
# MAGIC   reference, so every run recomputes it from scratch
# MAGIC   (`CREATE OR REPLACE`) — idempotent and restatement-proof by
# MAGIC   construction, with no incremental bookkeeping to get wrong.
# MAGIC - **A miss is data.** A security the master can't identify is kept
# MAGIC   and flagged (`instrument_status`), never dropped — same rule the
# MAGIC   master itself applies (its Unknown bucket), one layer up.

# COMMAND ----------

# MAGIC %pip install pydantic>=2.7

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import os
import sys
from pathlib import Path

# This notebook lives at <repo>/spark/; the ingest package at <repo>/ingest/src
# and the reference package at <repo>/reference/src. Reference is what silver
# actually consumes; ingest stays on the path for consistency with bronze.
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "ingest", "src")))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "reference", "src")))

from parvum_reference.ownership import ownership_bridge
from parvum_reference.securities_master import load_master

SCHEMA = "workspace.parvum"

# The master is data, not code: it is *landed* into the volume by
# `make land-master` (the workspace has no egress to call OpenFIGI itself).
# The ownership graph, by contrast, is code and arrives with this checkout.
MASTER_PATH = Path("/Volumes/workspace/parvum/landing/reference/securities_master.json")

# COMMAND ----------

# MAGIC %md ## Reference layers → temp views

# COMMAND ----------

# Typed load (validates every entry) rather than spark.read.json: the master
# is small, and the same parvum_reference model that wrote it should be the
# thing that reads it — one schema, owned in one place.
master_entries = load_master(MASTER_PATH)
master_df = spark.createDataFrame(  # noqa: F821
    [e.model_dump() for e in master_entries],
    schema="isin STRING, mapped BOOLEAN, figi STRING, name STRING, "
    "security_type STRING, market_sector STRING, ticker STRING, exchange_code STRING",
)
master_df.createOrReplaceTempView("ref_master")

owners_df = spark.createDataFrame(  # noqa: F821
    list(ownership_bridge()),
    schema="account_id STRING, client_id STRING, client_name STRING, "
    "ownership_pct DECIMAL(9,6)",
)
owners_df.createOrReplaceTempView("ref_owners")

print(f"master: {len(master_entries)} entries; bridge: {owners_df.count()} rows")

# COMMAND ----------

# MAGIC %md ## `silver_account_owners` — the bridge, materialised
# MAGIC
# MAGIC Tiny, but making the attribution *auditable*: which client owns which
# MAGIC account, at what effective fraction, per the resolver. Downstream
# MAGIC joins use it; a human questioning an attribution reads it.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_account_owners
    COMMENT 'Effective account ownership per client (resolved through the entity graph). Fractions per account sum to 1.'
    AS SELECT account_id, client_id, client_name, ownership_pct
    FROM ref_owners"""
)

# COMMAND ----------

# MAGIC %md ## `silver_positions` — one row per (date, account, security)
# MAGIC
# MAGIC Bronze deliberately keeps one row per position *per file*, and every
# MAGIC position arrives in two holdings formats — so the same Apple line
# MAGIC exists twice per day. Silver picks exactly one: semt.002 preferred
# MAGIC over MT535 (the richer message), file path as a final deterministic
# MAGIC tie-break. Whether the two copies *agree* is a data-quality
# MAGIC question for a later slice — conforming the grain comes first.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_positions
    COMMENT 'Conformed positions: one row per (as_of, account, security), enriched from the securities master. instrument_status flags what the master could not identify.'
    AS
    WITH deduped AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY as_of, account_id, security_scheme, security_id
            ORDER BY CASE source_format WHEN 'semt.002' THEN 1 WHEN 'MT535' THEN 2 ELSE 3 END,
                     file_path
        ) AS rn
        FROM {SCHEMA}.bronze_holdings
    )
    SELECT
        d.as_of,
        d.account_id,
        d.security_scheme,
        d.security_id,
        -- The master's name wins when it has one: it is the curated,
        -- canonical spelling. The feed's copy stays for lineage.
        COALESCE(m.name, d.security_name)      AS security_name,
        d.security_name                        AS feed_security_name,
        m.figi                                 AS figi,
        m.security_type                        AS security_type,
        -- 'Unknown' as a value, not NULL: the product surfaces an Unknown
        -- asset class with real numbers against it, and so do we.
        COALESCE(m.market_sector, 'Unknown')   AS asset_class,
        m.ticker                               AS ticker,
        CASE
            WHEN m.isin IS NULL THEN 'NOT_IN_MASTER'
            WHEN NOT m.mapped  THEN 'UNKNOWN'
            ELSE 'MAPPED'
        END                                    AS instrument_status,
        d.quantity,
        d.price_amount,
        d.price_currency,
        d.market_value,
        d.market_value_ccy,
        d.cost_basis,
        d.cost_basis_ccy,
        d.source_format                        AS source_format,
        d.file_path                            AS source_file,
        current_timestamp()                    AS rebuilt_at
    FROM deduped d
    LEFT JOIN ref_master m
        ON d.security_scheme = 'ISIN' AND d.security_id = m.isin
    WHERE d.rn = 1"""
)

# COMMAND ----------

# MAGIC %md ## `silver_position_owners` — the attribution
# MAGIC
# MAGIC Positions × ownership bridge: one row per (date, account, security,
# MAGIC owning client), with the position's value prorated by the client's
# MAGIC effective fraction. This is the table owner roll-ups read; the
# MAGIC un-prorated value stays one table over.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_position_owners
    COMMENT 'Owner-attributed positions: each silver position split across its ultimately-owning clients. owned_value = market_value × effective ownership fraction.'
    AS
    SELECT
        p.as_of,
        p.account_id,
        p.security_scheme,
        p.security_id,
        p.security_name,
        o.client_id,
        o.client_name,
        o.ownership_pct,
        CAST(p.market_value * o.ownership_pct AS DECIMAL(24,2)) AS owned_value,
        p.market_value_ccy,
        p.rebuilt_at
    FROM {SCHEMA}.silver_positions p
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)"""
)

# COMMAND ----------

# MAGIC %md ## What this run produced

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT
            (SELECT COUNT(*) FROM {SCHEMA}.silver_positions)        AS positions,
            (SELECT COUNT(DISTINCT as_of) FROM {SCHEMA}.silver_positions) AS days,
            (SELECT COUNT(*) FROM {SCHEMA}.silver_positions
             WHERE instrument_status <> 'MAPPED')                   AS not_mapped,
            (SELECT COUNT(*) FROM {SCHEMA}.silver_position_owners)  AS owner_rows"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT instrument_status, asset_class, COUNT(*) AS rows
        FROM {SCHEMA}.silver_positions
        GROUP BY instrument_status, asset_class
        ORDER BY rows DESC"""
    )
)
