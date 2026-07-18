# Databricks notebook source
# MAGIC %md
# MAGIC # Silver cash — balances and movements, owner-attributed
# MAGIC
# MAGIC Completes silver's coverage: a client's wealth is positions *plus*
# MAGIC cash, and this is the cash half. Unlike holdings, cash arrives in one
# MAGIC format (camt.053), so there is no cross-format dedupe here — bronze's
# MAGIC restatement handling already guarantees one row per fact.
# MAGIC
# MAGIC Principles (same as silver positions, D-023):
# MAGIC - **One grain per table**; owner attribution in separate tables, so
# MAGIC   summing an amount can never double-count a shared account.
# MAGIC - **Full rebuild** every run — a pure projection of bronze × the
# MAGIC   ownership bridge.
# MAGIC - **Native currency.** FQ5521's EUR stays EUR: converting needs an FX
# MAGIC   rate source we don't have, and silver states facts, it doesn't
# MAGIC   invent them. Cross-currency totals are a gold-layer concern with a
# MAGIC   real rates source behind them.

# COMMAND ----------

# MAGIC %pip install pydantic>=2.7

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import os
import sys

# Same layout contract as the sibling notebooks: repo checkout, packages
# reached via sys.path (a git_source job run installs nothing).
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "ingest", "src")))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "reference", "src")))

from parvum_reference.ownership import ownership_bridge

SCHEMA = "workspace.parvum"

# COMMAND ----------

# MAGIC %md ## The ownership bridge → temp view
# MAGIC
# MAGIC Built from code (the graph rides the checkout), identical to the
# MAGIC positions notebook. `silver_account_owners` is (re)written there; this
# MAGIC notebook only *reads* the resolver, so the two tasks stay independent
# MAGIC and can run in either order after bronze.

# COMMAND ----------

owners_df = spark.createDataFrame(  # noqa: F821
    list(ownership_bridge()),
    schema="account_id STRING, client_id STRING, client_name STRING, "
    "ownership_pct DECIMAL(9,6)",
)
owners_df.createOrReplaceTempView("ref_owners")

# COMMAND ----------

# MAGIC %md ## `silver_cash_balances` — one row per (date, account, balance type)

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_cash_balances
    COMMENT 'Conformed cash balances: one row per (as_of, account, balance_type), native currency. No FX conversion at this layer.'
    AS
    SELECT
        as_of,
        account_id,
        balance_type,
        amount,
        currency,
        file_path              AS source_file,
        current_timestamp()    AS rebuilt_at
    FROM {SCHEMA}.bronze_cash_balances"""
)

# COMMAND ----------

# MAGIC %md ## `silver_cash_transactions` — one row per (date, account, transaction)
# MAGIC
# MAGIC Bronze carries the feed's duplicates verbatim (the DUPLICATE_TRANSACTION
# MAGIC defect: the same movement sent twice under one reference). A reference
# MAGIC is unique by definition, so collapsing the copies IS the conformance —
# MAGIC but silently, it would also hide a defect the quality layer needs to
# MAGIC count. So the collapse stays visible: `source_row_count` says how many
# MAGIC bronze rows became this one, and `source_disagrees` flags groups whose
# MAGIC copies did not even agree (probing found 6 of the 80 duplicate pairs
# MAGIC differ on settlement_date by one day — DUPLICATE_TRANSACTION colliding
# MAGIC with SETTLEMENT_SHIFT on the same movement). Where copies disagree the
# MAGIC pick is deterministic — earliest settlement date, the conservative
# MAGIC claim — and the flag hands the conflict to the quality layer instead
# MAGIC of resolving it in silence.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_cash_transactions
    COMMENT 'Conformed cash movements: one row per (as_of, account, transaction_id), native currency. amount is as received (unsigned, direction in type); signed_amount applies the direction. source_row_count > 1 marks collapsed feed duplicates; source_disagrees marks copies that conflicted.'
    AS
    SELECT
        as_of,
        account_id,
        transaction_id,
        MAX(type)              AS type,
        MAX(trade_date)        AS trade_date,
        MIN(settlement_date)   AS settlement_date,
        MAX(amount)            AS amount,
        -- The feed stores amounts unsigned with direction in the type
        -- (camt.053 CdtDbtInd); the debit set mirrors DEBIT_TYPES in
        -- parvum_ingest/formats/camt053.py. Conformance means doing this
        -- once, here — not in every downstream SUM.
        MAX(CASE WHEN type IN ('BUY', 'FEE', 'TRANSFER_OUT')
                 THEN -amount ELSE amount END) AS signed_amount,
        MAX(currency)          AS currency,
        MAX(description)       AS description,
        COUNT(*)               AS source_row_count,
        (COUNT(DISTINCT type) > 1 OR COUNT(DISTINCT trade_date) > 1
         OR COUNT(DISTINCT settlement_date) > 1 OR COUNT(DISTINCT amount) > 1
         OR COUNT(DISTINCT currency) > 1 OR COUNT(DISTINCT description) > 1)
                               AS source_disagrees,
        MAX(file_path)         AS source_file,
        current_timestamp()    AS rebuilt_at
    FROM {SCHEMA}.bronze_cash_entries
    GROUP BY as_of, account_id, transaction_id"""
)

# COMMAND ----------

# MAGIC %md ## Owner attribution — same proration as positions
# MAGIC
# MAGIC Amount × the client's effective fraction, computed once here so gold
# MAGIC only ever sums. Balances × owners answers "each family's cash";
# MAGIC transactions × owners answers "each family's income and charges".

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_cash_balance_owners
    COMMENT 'Cash balances split across ultimately-owning clients. owned_amount = amount × effective ownership fraction.'
    AS
    SELECT
        b.as_of,
        b.account_id,
        b.balance_type,
        o.client_id,
        o.client_name,
        o.ownership_pct,
        CAST(b.amount * o.ownership_pct AS DECIMAL(24,2)) AS owned_amount,
        b.currency,
        b.rebuilt_at
    FROM {SCHEMA}.silver_cash_balances b
    JOIN ref_owners o USING (account_id)"""
)

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.silver_cash_transaction_owners
    COMMENT 'Cash movements split across ultimately-owning clients. owned_amount = amount × effective ownership fraction.'
    AS
    SELECT
        t.as_of,
        t.account_id,
        t.transaction_id,
        t.type,
        o.client_id,
        o.client_name,
        o.ownership_pct,
        CAST(t.signed_amount * o.ownership_pct AS DECIMAL(24,2)) AS owned_amount,
        t.currency,
        t.rebuilt_at
    FROM {SCHEMA}.silver_cash_transactions t
    JOIN ref_owners o USING (account_id)"""
)

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)
# MAGIC
# MAGIC Reapplied after every rebuild — `CREATE OR REPLACE` wipes them.
# MAGIC Escaping is SQL-standard quote doubling; this warehouse rejects
# MAGIC backslash escapes (learned live, catalog-docs slice).

# COMMAND ----------

COLUMN_COMMENTS = {
    "silver_cash_balances": {
        "as_of": "Statement date. Grain: one row per (as_of, account_id, balance_type)",
        "account_id": "Custodial account identifier (see silver_account_owners for whose it is)",
        "balance_type": "OPENING | CLOSING, from the camt.053 balance code",
        "amount": "Balance in native currency (NOT prorated — see silver_cash_balance_owners)",
        "currency": "The account's cash currency — no FX conversion at this layer",
        "source_file": "Volume path of the source camt.053 file — lineage into bronze",
        "rebuilt_at": "When this silver rebuild ran (UTC)",
    },
    "silver_cash_transactions": {
        "as_of": "Statement date. Grain: one row per (as_of, account_id, transaction_id)",
        "account_id": "Custodial account identifier",
        "transaction_id": "Transaction reference from the feed",
        "type": "Movement type as received (dividend, fee, transfer, …)",
        "trade_date": "Trade/booking date",
        "settlement_date": "Settlement/value date",
        "amount": "Movement as received: unsigned, direction in type (camt.053 CdtDbtInd convention)",
        "signed_amount": "amount with direction applied: negative for BUY/FEE/TRANSFER_OUT. The column downstream sums should use",
        "currency": "Currency of amount — no FX conversion at this layer",
        "description": "Free-text narrative from the feed",
        "source_row_count": "Bronze rows collapsed into this one: 1 normally, >1 where the feed sent a duplicate (kept visible for the quality layer)",
        "source_disagrees": "TRUE when the collapsed copies conflicted (e.g. shifted settlement date); the pick is deterministic, the conflict is the quality layer's to explain",
        "source_file": "Volume path of the source camt.053 file — lineage into bronze",
        "rebuilt_at": "When this silver rebuild ran (UTC)",
    },
    "silver_cash_balance_owners": {
        "as_of": "Statement date. Grain: one row per (as_of, account_id, balance_type, client)",
        "account_id": "Custodial account the balance belongs to",
        "balance_type": "OPENING | CLOSING",
        "client_id": "Ultimately-owning client this row attributes cash to",
        "client_name": "Display name of the owning client",
        "ownership_pct": "This client's effective fraction of the account",
        "owned_amount": "amount × ownership_pct — sums back to the account balance across its owners",
        "currency": "Native currency of the balance",
        "rebuilt_at": "When this silver rebuild ran (UTC)",
    },
    "silver_cash_transaction_owners": {
        "as_of": "Statement date. Grain: one row per (as_of, account_id, transaction_id, client)",
        "account_id": "Custodial account the movement occurred in",
        "transaction_id": "Transaction reference from the feed",
        "type": "Movement type as received",
        "client_id": "Ultimately-owning client this row attributes the movement to",
        "client_name": "Display name of the owning client",
        "ownership_pct": "This client's effective fraction of the account",
        "owned_amount": "signed_amount × ownership_pct — sums back to the signed movement across its owners",
        "currency": "Native currency of the movement",
        "rebuilt_at": "When this silver rebuild ran (UTC)",
    },
}

for _table, _comments in COLUMN_COMMENTS.items():
    for _col, _comment in _comments.items():
        _escaped = _comment.replace("'", "''")
        spark.sql(  # noqa: F821
            f"ALTER TABLE {SCHEMA}.{_table} ALTER COLUMN {_col} COMMENT '{_escaped}'"
        )
print(f"column comments applied to {len(COLUMN_COMMENTS)} cash tables")

# COMMAND ----------

# MAGIC %md ## What this run produced

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT
            (SELECT COUNT(*) FROM {SCHEMA}.silver_cash_balances)           AS balances,
            (SELECT COUNT(*) FROM {SCHEMA}.silver_cash_transactions)       AS transactions,
            (SELECT COUNT(*) FROM {SCHEMA}.silver_cash_balance_owners)     AS balance_owner_rows,
            (SELECT COUNT(*) FROM {SCHEMA}.silver_cash_transaction_owners) AS txn_owner_rows,
            (SELECT COUNT(DISTINCT currency) FROM {SCHEMA}.silver_cash_balances) AS currencies"""
    )
)
