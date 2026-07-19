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
# MAGIC exists twice per day. Silver picks exactly one: **semt.002 preferred
# MAGIC over MT535, chosen per (date, account) as a whole delivery**, file
# MAGIC path as a final deterministic tie-break within that chosen format.
# MAGIC Whether the two copies *agree* is a data-quality question for a later
# MAGIC slice (`dq_holdings_recon`, which compares bronze directly) —
# MAGIC conforming the grain comes first, and conforming it *by row* rather
# MAGIC than *by file* was a bug, not a milder version of the same choice: a
# MAGIC row whose identifier a defect corrupted (MISTYPED_ISIN) no longer
# MAGIC shares a key with its sibling in the other format, so a row-level
# MAGIC "prefer semt.002" lets *both* copies survive under two different
# MAGIC identifiers — silently double-counting that position's value in
# MAGIC every downstream sum. Found live: American Express duplicated across
# MAGIC `US0258161093` (MT535, correct) and `US0258161092` (semt.002, the
# MAGIC defect's bumped check digit), $4,585,899.28 counted twice. Choosing
# MAGIC the winning *file* first makes this structurally impossible — a
# MAGIC corrupted identifier still lands under the wrong ISIN (a real,
# MAGIC findable problem, exactly what `dq_holdings_recon` exists to catch),
# MAGIC but never as a second copy of the same dollar.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_positions
    COMMENT 'Conformed positions: one row per (as_of, account, security), enriched from the securities master. instrument_status flags what the master could not identify.'
    AS
    WITH file_choice AS (
        -- One winning format per (date, account): semt.002 if it delivered
        -- any row that day, else MT535. A whole-file choice, not a
        -- per-security one — see the note above on why that distinction is
        -- the whole fix.
        SELECT as_of, account_id,
               MIN_BY(source_format,
                      CASE source_format WHEN 'semt.002' THEN 1 WHEN 'MT535' THEN 2 ELSE 3 END
               ) AS source_format
        FROM {SCHEMA}.bronze_holdings
        GROUP BY as_of, account_id
    ),
    chosen AS (
        SELECT h.*
        FROM {SCHEMA}.bronze_holdings h
        JOIN file_choice c USING (as_of, account_id, source_format)
    ),
    deduped AS (
        -- Residual tie-break for a genuine same-format re-delivery (e.g. a
        -- re-land): file path, deterministic. Not expected to ever see rn>1
        -- in practice, since a chosen file's own rows are already unique by
        -- security within themselves.
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY as_of, account_id, security_scheme, security_id
            ORDER BY file_path
        ) AS rn
        FROM chosen
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

# MAGIC %md ## Column descriptions (Unity Catalog metadata)
# MAGIC
# MAGIC `CREATE OR REPLACE` rebuilds each table from scratch — including its
# MAGIC metadata — so column comments are (re)applied after every rebuild, from
# MAGIC one dict. A commented column list on the CTAS itself would be neater,
# MAGIC but that syntax does not parse on this warehouse (probed before
# MAGIC building); ALTER afterwards is the supported route.

# COMMAND ----------

COLUMN_COMMENTS = {
    "silver_positions": {
        "as_of": "Position date. Grain: one row per (as_of, account_id, security)",
        "account_id": "Custodial account identifier (see silver_account_owners for whose it is)",
        "security_scheme": "Identifier scheme of security_id (ISIN for anything the master can enrich)",
        "security_id": "Security identifier, from the preferred feed copy",
        "security_name": "Canonical name — the master's when mapped, else the feed's",
        "feed_security_name": "Name exactly as the feed carried it (lineage for the COALESCE above)",
        "figi": "FIGI from the securities master; NULL when not mapped",
        "security_type": "Instrument type from the master (e.g. Common Stock)",
        "asset_class": "Market sector from the master; literal Unknown when the master cannot say",
        "ticker": "Ticker from the master; NULL when not mapped",
        "instrument_status": "MAPPED | UNKNOWN (in master, unmappable) | NOT_IN_MASTER (identifier the master has never seen — where mistyped-identifier defects surface)",
        "quantity": "Units held, from the preferred feed copy",
        "price_amount": "Unit price, from the preferred feed copy",
        "price_currency": "Currency of price_amount",
        "market_value": "Market value of the full position (NOT prorated — see silver_position_owners)",
        "market_value_ccy": "Currency of market_value",
        "cost_basis": "Cost basis, from the preferred feed copy",
        "cost_basis_ccy": "Currency of cost_basis",
        "source_format": "Which feed copy won the dedupe: semt.002 preferred over MT535",
        "source_file": "Volume path of the winning file — lineage into bronze",
        "rebuilt_at": "When this silver rebuild ran (UTC); identical for all rows of a rebuild",
    },
    "silver_account_owners": {
        "account_id": "Custodial account identifier",
        "client_id": "Ultimately-owning client, resolved through the entity graph",
        "client_name": "Display name of the owning client",
        "ownership_pct": "Effective ownership fraction; per account these sum to exactly 1",
    },
    "silver_position_owners": {
        "as_of": "Position date. Grain: one row per (as_of, account_id, security, client)",
        "account_id": "Custodial account the position sits in",
        "security_scheme": "Identifier scheme of security_id",
        "security_id": "Security identifier",
        "security_name": "Canonical security name (as in silver_positions)",
        "client_id": "Ultimately-owning client this row attributes value to",
        "client_name": "Display name of the owning client",
        "ownership_pct": "This client's effective fraction of the account",
        "owned_value": "market_value × ownership_pct — sums back to market_value across an account's owners",
        "market_value_ccy": "Currency of owned_value",
        "rebuilt_at": "When this silver rebuild ran (UTC)",
    },
}

for _table, _comments in COLUMN_COMMENTS.items():
    for _col, _comment in _comments.items():
        _escaped = _comment.replace("'", "''")
        spark.sql(  # noqa: F821
            f"ALTER TABLE {SCHEMA}.{_table} ALTER COLUMN {_col} COMMENT '{_escaped}'"
        )
print(f"column comments applied to {len(COLUMN_COMMENTS)} silver tables")

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
