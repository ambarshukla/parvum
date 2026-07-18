# Databricks notebook source
# MAGIC %md
# MAGIC # Gold — the reports a person reads
# MAGIC
# MAGIC Everything below silver is plumbing; these four tables are the product:
# MAGIC each family's wealth over time, what it's made of, what it earned, and
# MAGIC what its biggest positions are. Gold only *sums and shapes* — every
# MAGIC number here traces to silver rows that trace to bronze files, the
# MAGIC proration was done once in silver, and the quality layer's verdicts
# MAGIC ride along as a flag rather than being asserted anew.
# MAGIC
# MAGIC Principles:
# MAGIC - **One currency for headlines, labelled honestly.** Totals are USD,
# MAGIC   converted at each day's ECB reference rate; every row carries the
# MAGIC   rate it used *and the day that rate was published* (a Saturday
# MAGIC   valuation carries Friday's rate, and says so — D-026).
# MAGIC - **Quality is a column, not a footnote.** `books_reconcile` on the
# MAGIC   wealth table is the DQ layer's conformed-cash verdict for every
# MAGIC   account the client owns that day.
# MAGIC - **Full rebuild**, like all derived layers here.

# COMMAND ----------

# MAGIC %pip install pydantic>=2.7

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "ingest", "src")))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "reference", "src")))

from parvum_reference.ecb import fill_forward, load_rates

SCHEMA = "workspace.parvum"
RATES_PATH = Path("/Volumes/workspace/parvum/landing/reference/fx_rates.json")

# COMMAND ----------

# MAGIC %md ## FX → a rate for every business date in scope
# MAGIC
# MAGIC The landed store holds only what the ECB published; `fill_forward`
# MAGIC completes the calendar at read time and names each rate's publication
# MAGIC day. The date range comes from the data, not a constant — gold should
# MAGIC never fail because the pile grew.

# COMMAND ----------

lo, hi = spark.sql(  # noqa: F821
    f"SELECT MIN(as_of), MAX(as_of) FROM {SCHEMA}.silver_positions"
).first()

rates = fill_forward(load_rates(RATES_PATH), lo, hi)
fx_df = spark.createDataFrame(  # noqa: F821
    [(day, str(rate), published) for day, (rate, published) in sorted(rates.items())],
    schema="as_of DATE, eur_usd_str STRING, fx_rate_date DATE",
)
fx_df.createOrReplaceTempView("fx_raw")
spark.sql(  # noqa: F821
    "CREATE OR REPLACE TEMP VIEW fx AS "
    "SELECT as_of, CAST(eur_usd_str AS DECIMAL(12,6)) AS eur_usd, fx_rate_date FROM fx_raw"
)
print(f"fx: {len(rates)} days, {lo} -> {hi}")

# COMMAND ----------

# MAGIC %md ## `gold_client_wealth` — the headline number
# MAGIC
# MAGIC Grain: one row per (client, date). Positions plus closing cash, each
# MAGIC converted at that date's rate. Conversion is per-currency: USD passes
# MAGIC through untouched, EUR multiplies by the day's EUR→USD rate — the
# MAGIC only two currencies the universe holds, enforced loudly below.

# COMMAND ----------

# A currency this notebook doesn't know how to convert must stop the run,
# not silently pass through at 1:1.
unknown = spark.sql(  # noqa: F821
    f"""SELECT DISTINCT ccy FROM (
        SELECT market_value_ccy AS ccy FROM {SCHEMA}.silver_position_owners
        UNION ALL
        SELECT currency FROM {SCHEMA}.silver_cash_balance_owners
        UNION ALL
        SELECT currency FROM {SCHEMA}.silver_cash_transaction_owners
    ) WHERE ccy NOT IN ('USD', 'EUR')"""
).collect()
if unknown:
    raise ValueError(f"currencies gold cannot convert: {[r['ccy'] for r in unknown]}")

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_client_wealth
    COMMENT 'Per client per day: total wealth in USD (positions + closing cash, converted at that day''s ECB reference rate). books_reconcile is the DQ layer''s cash verdict across the client''s accounts.'
    AS
    WITH pos AS (
        SELECT p.as_of, p.client_id, p.client_name,
               SUM(CASE WHEN p.market_value_ccy = 'USD' THEN p.owned_value
                        ELSE p.owned_value * f.eur_usd END) AS positions_usd
        FROM {SCHEMA}.silver_position_owners p
        JOIN fx f USING (as_of)
        GROUP BY p.as_of, p.client_id, p.client_name
    ),
    cash AS (
        SELECT b.as_of, b.client_id,
               SUM(CASE WHEN b.currency = 'USD' THEN b.owned_amount
                        ELSE b.owned_amount * f.eur_usd END) AS cash_usd
        FROM {SCHEMA}.silver_cash_balance_owners b
        JOIN fx f USING (as_of)
        WHERE b.balance_type = 'CLOSING'
        GROUP BY b.as_of, b.client_id
    ),
    quality AS (
        -- every() over the client's accounts: one broken account-day marks
        -- the client's day unreconciled. Verdicts come from dq_cash_integrity.
        SELECT d.as_of, o.client_id, every(d.conformed_consistent) AS books_reconcile
        FROM {SCHEMA}.dq_cash_integrity d
        JOIN {SCHEMA}.silver_account_owners o USING (account_id)
        GROUP BY d.as_of, o.client_id
    )
    SELECT
        p.as_of,
        p.client_id,
        p.client_name,
        CAST(p.positions_usd AS DECIMAL(24,2))                       AS positions_usd,
        CAST(COALESCE(c.cash_usd, 0) AS DECIMAL(24,2))               AS cash_usd,
        CAST(p.positions_usd + COALESCE(c.cash_usd, 0)
             AS DECIMAL(24,2))                                       AS total_wealth_usd,
        f.eur_usd                                                    AS fx_rate_used,
        f.fx_rate_date,
        COALESCE(q.books_reconcile, TRUE)                            AS books_reconcile,
        current_timestamp()                                          AS rebuilt_at
    FROM pos p
    LEFT JOIN cash c   USING (as_of, client_id)
    LEFT JOIN quality q USING (as_of, client_id)
    JOIN fx f USING (as_of)"""
)

# COMMAND ----------

# MAGIC %md ## `gold_asset_allocation` — what the wealth is made of
# MAGIC
# MAGIC Grain: one row per (client, date, asset class). Positions carry the
# MAGIC master's class ('Unknown' where the master couldn't say — those are
# MAGIC real client holdings and belong in the report, D-022); cash appears
# MAGIC as its own 'Cash' class, the way product allocation views show it.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_asset_allocation
    COMMENT 'Per client per day per asset class: USD value and share of that day''s total wealth. Cash is a class; Unknown is a class (unmapped instruments stay visible).'
    AS
    WITH classed AS (
        SELECT po.as_of, po.client_id, po.client_name, sp.asset_class,
               SUM(CASE WHEN po.market_value_ccy = 'USD' THEN po.owned_value
                        ELSE po.owned_value * f.eur_usd END) AS value_usd
        FROM {SCHEMA}.silver_position_owners po
        JOIN {SCHEMA}.silver_positions sp
            USING (as_of, account_id, security_scheme, security_id)
        JOIN fx f USING (as_of)
        GROUP BY po.as_of, po.client_id, po.client_name, sp.asset_class
        UNION ALL
        SELECT b.as_of, b.client_id, b.client_name, 'Cash',
               SUM(CASE WHEN b.currency = 'USD' THEN b.owned_amount
                        ELSE b.owned_amount * f.eur_usd END)
        FROM {SCHEMA}.silver_cash_balance_owners b
        JOIN fx f USING (as_of)
        WHERE b.balance_type = 'CLOSING'
        GROUP BY b.as_of, b.client_id, b.client_name
    )
    SELECT
        c.as_of,
        c.client_id,
        c.client_name,
        c.asset_class,
        CAST(c.value_usd AS DECIMAL(24,2))                            AS value_usd,
        CAST(c.value_usd / SUM(c.value_usd) OVER (PARTITION BY c.as_of, c.client_id)
             AS DECIMAL(9,6))                                         AS weight,
        current_timestamp()                                           AS rebuilt_at
    FROM classed c"""
)

# COMMAND ----------

# MAGIC %md ## `gold_income` — what the wealth earned
# MAGIC
# MAGIC Grain: one row per (client, month, income type). Dividends and
# MAGIC interest only — fees and trades are flows, not income. Amounts are
# MAGIC the owner-prorated signed values, converted at each movement's date.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_income
    COMMENT 'Per client per month: dividend and interest income in USD, owner-prorated, converted at each movement''s date. Grain: client × month × type.'
    AS
    SELECT
        t.client_id,
        t.client_name,
        DATE_TRUNC('month', t.as_of)                     AS month,
        t.type,
        CAST(SUM(CASE WHEN t.currency = 'USD' THEN t.owned_amount
                      ELSE t.owned_amount * f.eur_usd END)
             AS DECIMAL(24,2))                           AS income_usd,
        COUNT(*)                                         AS movements,
        current_timestamp()                              AS rebuilt_at
    FROM {SCHEMA}.silver_cash_transaction_owners t
    JOIN fx f USING (as_of)
    WHERE t.type IN ('DIVIDEND', 'INTEREST')
    GROUP BY t.client_id, t.client_name, DATE_TRUNC('month', t.as_of), t.type"""
)

# COMMAND ----------

# MAGIC %md ## `gold_top_holdings` — the biggest positions, latest day
# MAGIC
# MAGIC Grain: one row per (client, rank), top 10 by owned USD value on the
# MAGIC most recent date. Weight is the share of the client's *positions*
# MAGIC value (the conventional holdings-report basis), not total wealth.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_top_holdings
    COMMENT 'Per client: top 10 positions by owned USD value on the latest date, with instrument identity and share of the client''s positions value.'
    AS
    WITH latest AS (
        SELECT MAX(as_of) AS as_of FROM {SCHEMA}.silver_position_owners
    ),
    valued AS (
        SELECT po.as_of, po.client_id, po.client_name,
               po.security_scheme, po.security_id, po.security_name,
               sp.asset_class, sp.instrument_status, po.account_id,
               CASE WHEN po.market_value_ccy = 'USD' THEN po.owned_value
                    ELSE po.owned_value * f.eur_usd END AS owned_usd
        FROM {SCHEMA}.silver_position_owners po
        JOIN latest USING (as_of)
        JOIN {SCHEMA}.silver_positions sp
            USING (as_of, account_id, security_scheme, security_id)
        JOIN fx f USING (as_of)
    ),
    -- One client can hold the same security through two accounts; a
    -- holdings report shows the security once, summed.
    per_security AS (
        SELECT as_of, client_id, client_name, security_scheme, security_id,
               MAX(security_name) AS security_name, MAX(asset_class) AS asset_class,
               SUM(owned_usd) AS owned_usd
        FROM valued
        GROUP BY as_of, client_id, client_name, security_scheme, security_id
    ),
    ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY owned_usd DESC,
                                  security_id) AS rank,
               SUM(owned_usd) OVER (PARTITION BY client_id) AS client_positions_usd
        FROM per_security
    )
    SELECT
        as_of,
        client_id,
        client_name,
        rank,
        security_name,
        security_scheme,
        security_id,
        asset_class,
        CAST(owned_usd AS DECIMAL(24,2))                    AS owned_usd,
        CAST(owned_usd / client_positions_usd AS DECIMAL(9,6)) AS weight,
        current_timestamp()                                 AS rebuilt_at
    FROM ranked
    WHERE rank <= 10"""
)

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)

# COMMAND ----------

COLUMN_COMMENTS = {
    "gold_client_wealth": {
        "as_of": "Valuation date. Grain: one row per (client, date)",
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "positions_usd": "Owner-prorated securities value in USD, converted at fx_rate_used",
        "cash_usd": "Owner-prorated closing cash in USD, converted at fx_rate_used",
        "total_wealth_usd": "positions_usd + cash_usd — the headline number",
        "fx_rate_used": "EUR→USD ECB reference rate applied to this date's EUR amounts",
        "fx_rate_date": "The day fx_rate_used was published; earlier than as_of means carried forward (weekend/holiday) — labelled, not hidden",
        "books_reconcile": "TRUE when the DQ layer's conformed cash check passes for every account this client owns on this date",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_asset_allocation": {
        "as_of": "Valuation date. Grain: one row per (client, date, asset_class)",
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "asset_class": "Instrument class from the securities master; 'Cash' for cash; 'Unknown' where the master could not identify the instrument (kept visible, D-022)",
        "value_usd": "Owner-prorated USD value of this class on this date",
        "weight": "value_usd / the client's total wealth that date; weights per (client, date) sum to 1",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_income": {
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "month": "Calendar month of the income. Grain: one row per (client, month, type)",
        "type": "DIVIDEND or INTEREST — income only; fees and trades are flows, not income",
        "income_usd": "Owner-prorated income in USD, converted at each movement's date",
        "movements": "Number of underlying cash movements in the month",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_top_holdings": {
        "as_of": "The latest valuation date in silver when this rebuild ran",
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "rank": "1 = largest owned USD value. Grain: one row per (client, rank), top 10",
        "security_name": "Canonical instrument name (master's where mapped)",
        "security_scheme": "Identifier scheme of security_id",
        "security_id": "Security identifier",
        "asset_class": "Instrument class from the securities master ('Unknown' if unmapped)",
        "owned_usd": "This client's owner-prorated USD value, summed across their accounts",
        "weight": "owned_usd / the client's total positions value (conventional holdings-report basis)",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
}

for _table, _comments in COLUMN_COMMENTS.items():
    for _col, _comment in _comments.items():
        _escaped = _comment.replace("'", "''")
        spark.sql(  # noqa: F821
            f"ALTER TABLE {SCHEMA}.{_table} ALTER COLUMN {_col} COMMENT '{_escaped}'"
        )
print(f"column comments applied to {len(COLUMN_COMMENTS)} gold tables")

# COMMAND ----------

# MAGIC %md ## The report, as of the latest day

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, total_wealth_usd, positions_usd, cash_usd,
               fx_rate_used, fx_rate_date, books_reconcile
        FROM {SCHEMA}.gold_client_wealth
        WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_client_wealth)
        ORDER BY total_wealth_usd DESC"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, asset_class, value_usd, weight
        FROM {SCHEMA}.gold_asset_allocation
        WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_asset_allocation)
        ORDER BY client_name, value_usd DESC"""
    )
)
