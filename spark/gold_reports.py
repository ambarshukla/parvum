# Databricks notebook source
# MAGIC %md
# MAGIC # Gold — the reports a person reads
# MAGIC
# MAGIC Everything below silver is plumbing; these five tables are the product:
# MAGIC each family's wealth over time, what it's made of, what it earned, what
# MAGIC its biggest positions are, and who owns which accounts. Gold only *sums
# MAGIC and shapes* — every
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

import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "ingest", "src")))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "reference", "src")))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..", "alts-hitl", "src")))

from parvum_alts_hitl.parsing import parse_decimal
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

# MAGIC %md ## Alts (private-fund) holdings — small data, computed in Python
# MAGIC
# MAGIC Same "collect, compute locally, `createDataFrame` back" pattern the FX
# MAGIC and IRR sections use: a couple of funds and a few dozen documents,
# MAGIC trivial to bring to the driver. Two things come out of it:
# MAGIC
# MAGIC - **`gold_alts_holdings`**, a standalone detail table (committed,
# MAGIC   called, distributed, unfunded, NAV, MOIC per client per fund) — the
# MAGIC   private-markets analogue of `gold_top_holdings`.
# MAGIC - **`alts_daily`**, a per-client daily NAV series that `gold_client_wealth`
# MAGIC   and `gold_asset_allocation` below both join into, so alts stop being
# MAGIC   invisible to the headline wealth number.
# MAGIC
# MAGIC **Only confirmed values count.** A document still sitting in
# MAGIC `needs_review` with no human decision yet contributes nothing here —
# MAGIC the same DQ-honesty stance the rest of gold takes (a number nobody has
# MAGIC signed off on doesn't get to move a client's reported wealth).
# MAGIC `pending_review_documents` surfaces how many are waiting, per fund, so
# MAGIC that omission is visible rather than silent.
# MAGIC
# MAGIC **NAV updates quarterly, wealth is reported daily.** Without
# MAGIC forward-filling, alts would vanish from `gold_client_wealth` on every
# MAGIC date that isn't an exact statement date. The most recent confirmed NAV
# MAGIC holds until the next statement supersedes it — exactly how a real
# MAGIC reported mark behaves. Worth naming, not hiding: on the day a new
# MAGIC statement's date lands, `daily_twr_return` will show a real, not fake,
# MAGIC jump — a private-markets NAV mark landing all at once, the same
# MAGIC "flat-then-a-jump" shape the 13F price data already produces elsewhere
# MAGIC in this project, not a defect.
# MAGIC
# MAGIC **Amounts are treated as USD outright** — the two-fund universe
# MAGIC (`generate.py`'s `FUND_UNIVERSE`) is USD-only today and no document
# MAGIC schema carries a currency field to convert from; a non-USD fund would
# MAGIC need that added, not assumed away.

# COMMAND ----------

_alts_confirmed = spark.sql(  # noqa: F821
    f"""SELECT doc_type, confirmed_fields_json
    FROM {SCHEMA}.silver_alts_documents WHERE confirmed_fields_json IS NOT NULL"""
).collect()

_alts_pending = {
    row.fund_id: row.pending
    for row in spark.sql(  # noqa: F821
        f"""SELECT fund_id, COUNT(*) AS pending FROM {SCHEMA}.silver_alts_documents
        WHERE routing = 'needs_review' AND reviewed_status IS NULL GROUP BY fund_id"""
    ).collect()
}

_calls: dict[str, list[dict]] = {}
_dists: dict[str, list[dict]] = {}
_stmts: dict[str, list[dict]] = {}
_by_doc_type = {"capital_call": _calls, "distribution": _dists, "capital_account_statement": _stmts}
for _row in _alts_confirmed:
    _fields = json.loads(_row.confirmed_fields_json)
    _by_doc_type[_row.doc_type].setdefault(_fields["fund_id"], []).append(_fields)

_alts_fund_rows = []
_alts_nav_rows = []
for _fid in sorted(set(_calls) | set(_dists) | set(_stmts)):
    _fund_calls = sorted(_calls.get(_fid, []), key=lambda f: f["call_number"])
    _fund_dists = sorted(_dists.get(_fid, []), key=lambda f: f["distribution_number"])
    _fund_stmts = sorted(_stmts.get(_fid, []), key=lambda f: f["period_end"])
    _any_doc = (_fund_stmts or _fund_calls or _fund_dists)[0]

    _called = parse_decimal(_fund_calls[-1]["cumulative_called"]) if _fund_calls else Decimal(0)
    _distributed = (
        parse_decimal(_fund_dists[-1]["cumulative_distributed"]) if _fund_dists else Decimal(0)
    )

    if _fund_stmts:
        _latest = _fund_stmts[-1]
        _nav = parse_decimal(_latest["ending_balance"])
        _unfunded = parse_decimal(_latest["unfunded_commitment"])
        _commitment = parse_decimal(_latest["total_commitment"])
        _stmt_as_of = date.fromisoformat(_latest["period_end"])
    else:
        # No confirmed statement yet — fall back to what the calls imply.
        _nav = Decimal(0)
        _commitment = _called + (
            parse_decimal(_fund_calls[-1]["remaining_commitment"]) if _fund_calls else Decimal(0)
        )
        _unfunded = _commitment - _called
        _stmt_as_of = None

    _dates = []
    if _fund_calls:
        _dates.append(date.fromisoformat(_fund_calls[0]["call_date"]))
    if _fund_dists:
        _dates.append(date.fromisoformat(_fund_dists[0]["distribution_date"]))
    if _fund_stmts:
        _dates.append(date.fromisoformat(_fund_stmts[0]["period_end"]))

    # A ratio, owner-invariant (proration cancels in both numerator and
    # denominator) — stored as text and CAST later, the same trick
    # gold_performance_summary uses for IRR, since a Python Decimal division
    # can carry more digits than the target column.
    _moic = (_distributed + _nav) / _called if _called > 0 else None

    _alts_fund_rows.append(
        {
            "fund_id": _fid,
            "fund_name": _any_doc["fund_name"],
            "account_id": _any_doc["account_id"],
            "inception_date": min(_dates) if _dates else None,
            "as_of": _stmt_as_of,
            "total_commitment_usd": _commitment,
            "called_to_date_usd": _called,
            "distributed_to_date_usd": _distributed,
            "unfunded_commitment_usd": _unfunded,
            "current_nav_usd": _nav,
            "moic_str": str(_moic) if _moic is not None else None,
            "pending_review_documents": int(_alts_pending.get(_fid, 0)),
        }
    )
    for _stmt in _fund_stmts:
        _alts_nav_rows.append(
            {
                "fund_id": _fid,
                "account_id": _any_doc["account_id"],
                "statement_date": date.fromisoformat(_stmt["period_end"]),
                "nav_usd": parse_decimal(_stmt["ending_balance"]),
            }
        )

print(f"alts: {len(_alts_fund_rows)} funds, {len(_alts_nav_rows)} confirmed NAV marks")

# COMMAND ----------

spark.createDataFrame(  # noqa: F821
    _alts_fund_rows,
    schema="fund_id STRING, fund_name STRING, account_id STRING, inception_date DATE, "
    "as_of DATE, total_commitment_usd DECIMAL(24,2), called_to_date_usd DECIMAL(24,2), "
    "distributed_to_date_usd DECIMAL(24,2), unfunded_commitment_usd DECIMAL(24,2), "
    "current_nav_usd DECIMAL(24,2), moic_str STRING, pending_review_documents INT",
).createOrReplaceTempView("alts_fund_raw")

spark.createDataFrame(  # noqa: F821
    _alts_nav_rows,
    schema="fund_id STRING, account_id STRING, statement_date DATE, nav_usd DECIMAL(24,2)",
).createOrReplaceTempView("alts_nav_raw")

# Owner-prorated NAV per (client, statement date) — the input to alts_daily's
# forward fill below.
spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TEMP VIEW alts_nav_points AS
    SELECT o.client_id, n.statement_date,
           CAST(SUM(n.nav_usd * o.ownership_pct) AS DECIMAL(24,2)) AS nav_usd
    FROM alts_nav_raw n
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)
    GROUP BY o.client_id, n.statement_date"""
)

# COMMAND ----------

# MAGIC %md ### `gold_alts_holdings` — the detail behind the number
# MAGIC
# MAGIC Grain: one row per (client, fund). Owner-prorated the same way
# MAGIC everything else in gold is; `moic` and `pending_review_documents` are
# MAGIC ratios/counts, not money, so they are copied to every owner unprorated
# MAGIC (proration cancels out of a ratio, and a document count isn't anyone's
# MAGIC dollar amount to divide up).

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_alts_holdings
    COMMENT 'Owner-prorated private-fund holdings, one row per (client, fund): commitment, capital called and distributed to date, unfunded commitment, current NAV, and MOIC. Only confirmed (auto-accepted or human-reviewed) documents are reflected -- pending_review_documents counts what is deliberately left out.'
    AS
    SELECT
        o.client_id,
        o.client_name,
        f.fund_id,
        f.fund_name,
        f.account_id,
        f.inception_date,
        f.as_of,
        CAST(f.total_commitment_usd * o.ownership_pct AS DECIMAL(24,2))     AS total_commitment_usd,
        CAST(f.called_to_date_usd * o.ownership_pct AS DECIMAL(24,2))      AS called_to_date_usd,
        CAST(f.distributed_to_date_usd * o.ownership_pct AS DECIMAL(24,2)) AS distributed_to_date_usd,
        CAST(f.unfunded_commitment_usd * o.ownership_pct AS DECIMAL(24,2)) AS unfunded_commitment_usd,
        CAST(f.current_nav_usd * o.ownership_pct AS DECIMAL(24,2))         AS current_nav_usd,
        CAST(f.moic_str AS DECIMAL(14,6))                                  AS moic,
        f.pending_review_documents,
        current_timestamp()                                                AS rebuilt_at
    FROM alts_fund_raw f
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)"""
)

# COMMAND ----------

# MAGIC %md ### `alts_daily` — forward-filled NAV, one row per (client, date)
# MAGIC
# MAGIC Reused by both `gold_client_wealth` and `gold_asset_allocation` below.
# MAGIC The date grid is every date `silver_position_owners` already reports on,
# MAGIC UNIONed with the fund's own statement dates — a statement landing
# MAGIC *before* the wealth-reporting window even starts still has to seed the
# MAGIC forward fill, or its NAV would read as zero for the whole window
# MAGIC instead of "whatever the last confirmed mark said".

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TEMP VIEW alts_daily AS
    WITH wealth_dates AS (
        SELECT DISTINCT as_of, client_id, client_name FROM {SCHEMA}.silver_position_owners
    ),
    all_dates AS (
        SELECT as_of, client_id FROM wealth_dates
        UNION
        SELECT statement_date AS as_of, client_id FROM alts_nav_points
    ),
    joined AS (
        SELECT d.as_of, d.client_id, p.nav_usd
        FROM all_dates d
        LEFT JOIN alts_nav_points p ON p.client_id = d.client_id AND p.statement_date = d.as_of
    ),
    filled AS (
        SELECT as_of, client_id,
               COALESCE(LAST_VALUE(nav_usd, true) OVER (
                   PARTITION BY client_id ORDER BY as_of
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) AS alts_usd
        FROM joined
    )
    SELECT w.as_of, w.client_id, w.client_name, f.alts_usd
    FROM wealth_dates w
    JOIN filled f USING (as_of, client_id)"""
)

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
    COMMENT 'Per client per day: total wealth in USD (positions + closing cash + forward-filled alts NAV, converted at that day''s ECB reference rate). books_reconcile is the DQ layer''s cash verdict across the client''s accounts.'
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
        CAST(COALESCE(a.alts_usd, 0) AS DECIMAL(24,2))               AS alts_usd,
        CAST(p.positions_usd + COALESCE(c.cash_usd, 0) + COALESCE(a.alts_usd, 0)
             AS DECIMAL(24,2))                                       AS total_wealth_usd,
        f.eur_usd                                                    AS fx_rate_used,
        f.fx_rate_date,
        COALESCE(q.books_reconcile, TRUE)                            AS books_reconcile,
        current_timestamp()                                          AS rebuilt_at
    FROM pos p
    LEFT JOIN cash c     USING (as_of, client_id)
    LEFT JOIN alts_daily a USING (as_of, client_id)
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
        UNION ALL
        -- 'Alternatives' matches the color slot the web palette already
        -- reserves for this class (web/src/palette.ts ASSET_CLASS_SLOT) —
        -- picked to line up with that reservation, not coined fresh here.
        -- Already USD (see the alts section above) and already forward-filled
        -- to every wealth date; skipped for clients holding none, same as any
        -- other class never appears for a client with none of it.
        SELECT ad.as_of, ad.client_id, ad.client_name, 'Alternatives', ad.alts_usd
        FROM alts_daily ad
        WHERE ad.alts_usd > 0
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

# MAGIC %md ## `gold_performance` — the daily return chain
# MAGIC
# MAGIC Grain: one row per (client, date). Separates market return from the
# MAGIC client's own money: `external_flow_usd` is that day's net contribution
# MAGIC (positive) or withdrawal (negative), and `daily_twr_return` excludes it
# MAGIC — `(wealth_today − flow_today) / wealth_yesterday − 1`, the textbook
# MAGIC time-weighted-return definition. `twr_index_since_inception` chain-links
# MAGIC those daily returns via the standard log-sum trick (`EXP(SUM(LN(1+r)))`,
# MAGIC exact in Delta's window functions, no UDF needed) into a growth-of-$1
# MAGIC index: 1.0 at inception, > 1.0 means the *market* grew the account,
# MAGIC independent of what the client put in or took out. Inception is each
# MAGIC client's first date in `gold_client_wealth`, so `daily_twr_return` is
# MAGIC NULL and the index is exactly 1.0 on that first row — there is no prior
# MAGIC day to measure a return against.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_performance
    COMMENT 'Daily time-weighted return chain per client. daily_twr_return excludes that day''s external_flow_usd from the market-return calculation; twr_index_since_inception chain-links the daily returns into a growth-of-$1 index starting at 1.0 on the client''s first date.'
    AS
    WITH flows AS (
        SELECT t.as_of, t.client_id,
               SUM(CASE WHEN t.currency = 'USD' THEN t.owned_amount
                        ELSE t.owned_amount * f.eur_usd END) AS flow_usd
        FROM {SCHEMA}.silver_cash_transaction_owners t
        JOIN fx f USING (as_of)
        WHERE t.type IN ('TRANSFER_IN', 'TRANSFER_OUT')
        GROUP BY t.as_of, t.client_id
    ),
    joined AS (
        SELECT w.as_of, w.client_id, w.client_name, w.total_wealth_usd,
               COALESCE(fl.flow_usd, 0) AS external_flow_usd,
               LAG(w.total_wealth_usd) OVER (
                   PARTITION BY w.client_id ORDER BY w.as_of) AS prev_wealth_usd
        FROM {SCHEMA}.gold_client_wealth w
        LEFT JOIN flows fl USING (as_of, client_id)
    ),
    returns AS (
        SELECT *,
               CASE WHEN prev_wealth_usd IS NULL THEN NULL
                    ELSE (total_wealth_usd - external_flow_usd) / prev_wealth_usd - 1
               END AS daily_twr_return
        FROM joined
    )
    SELECT
        as_of,
        client_id,
        client_name,
        CAST(total_wealth_usd AS DECIMAL(24,2))                        AS total_wealth_usd,
        CAST(external_flow_usd AS DECIMAL(24,2))                       AS external_flow_usd,
        CAST(daily_twr_return AS DECIMAL(14,8))                        AS daily_twr_return,
        CAST(EXP(SUM(LN(1 + COALESCE(daily_twr_return, 0))) OVER (
            PARTITION BY client_id ORDER BY as_of
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
             AS DECIMAL(14,8))                                         AS twr_index_since_inception,
        current_timestamp()                                            AS rebuilt_at
    FROM returns"""
)

# COMMAND ----------

# MAGIC %md ## `gold_performance_summary` — the methodology comparison
# MAGIC
# MAGIC Grain: one row per client. Three answers to the same question —
# MAGIC "how did this account do since inception?" — computed three different
# MAGIC ways, on purpose:
# MAGIC
# MAGIC - **`twr_since_inception`** (time-weighted): `gold_performance`'s chained
# MAGIC   index minus one. Judges the *market*, blind to when the client's money
# MAGIC   moved — the fair way to grade a manager who doesn't control deposit
# MAGIC   timing.
# MAGIC - **`dietz_since_inception`** (Modified Dietz): the pre-computer
# MAGIC   approximation of the same idea — one formula over the whole period,
# MAGIC   with each flow weighted by the fraction of the period it was invested
# MAGIC   (`(days remaining in period) / (total days)`). Tracks TWR closely when
# MAGIC   flows are small relative to the portfolio; the gap between them *is*
# MAGIC   the approximation error.
# MAGIC - **`irr_since_inception_annualized`** (money-weighted, IRR/XIRR): the
# MAGIC   *investor's* actual experience — flow timing matters here on purpose,
# MAGIC   solved by bisection (root of the NPV-at-rate-r function; no external
# MAGIC   solver library needed) over each client's actual cash flow dates.
# MAGIC   Reported **annualized**, the universal IRR convention — TWR and Dietz
# MAGIC   above are *not* annualized (matching GIPS practice for sub-annual
# MAGIC   periods), so a short, volatile quarter's IRR reads far larger in
# MAGIC   magnitude than the other two. That gap is not a bug in either number;
# MAGIC   it is the annualization convention itself, and it is exactly the kind
# MAGIC   of "methodology difference" a performance report has to be able to
# MAGIC   explain rather than paper over.
# MAGIC
# MAGIC IRR needs root-finding, which SQL window functions can't do; computed in
# MAGIC Python from a small collected series (one row per client-date — a few
# MAGIC hundred rows, trivial to bring local) and joined back in, the same
# MAGIC compute-in-Python-then-`createDataFrame` pattern the FX section above
# MAGIC already uses.

# COMMAND ----------


def _xirr(cashflows: list[tuple]) -> float | None:
    """Annualized money-weighted return: the rate r solving NPV(r) = 0 for a
    series of (date, signed amount) cash flows, dated ACT/365 from the first
    flow. Bisection, not Newton's method — this is 3-5 clients computed once
    per gold rebuild, and bisection can't diverge the way Newton can on a
    poorly-behaved NPV curve. Returns None if the bracket [-99.99%, +1000%]
    doesn't contain a root — a legitimate "undefined for this flow pattern"
    outcome, not a defect to raise on.
    """
    t0 = cashflows[0][0]

    def npv(rate: float) -> float:
        return sum(
            float(amount) / (1 + rate) ** ((d - t0).days / 365.0) for d, amount in cashflows
        )

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


_perf_rows = (
    spark.sql(  # noqa: F821
        f"SELECT as_of, client_id, total_wealth_usd, external_flow_usd "
        f"FROM {SCHEMA}.gold_performance ORDER BY client_id, as_of"
    )
    .collect()
)
_by_client: dict[str, list] = {}
for _row in _perf_rows:
    _by_client.setdefault(_row.client_id, []).append(
        (_row.as_of, _row.total_wealth_usd, _row.external_flow_usd)
    )

_irr_rows = []
for _client_id, _series in _by_client.items():
    _d0, _v0, _ = _series[0]
    _dn, _vn, _ = _series[-1]
    # The inception day's own flow is already reflected in v0 (a statement
    # balance is always ex-flow, i.e. after that day's activity settled), so
    # it must not also appear as a separate investor cash flow — the same
    # boundary convention gold_performance's daily chain uses (its first
    # daily_twr_return is NULL for the identical reason).
    _cfs: list[tuple] = [(_d0, -float(_v0))]
    for _d, _, _flow in _series[1:]:
        if _flow != 0:
            _cfs.append((_d, -float(_flow)))
    _cfs.append((_dn, float(_vn)))
    _irr = _xirr(_cfs)
    _irr_rows.append((_client_id, str(_irr) if _irr is not None else None))

spark.createDataFrame(  # noqa: F821
    _irr_rows, schema="client_id STRING, irr_str STRING"
).createOrReplaceTempView("irr_raw")

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_performance_summary
    COMMENT 'One row per client: since-inception return by three methodologies (time-weighted, Modified Dietz, money-weighted IRR) — see docs/PERFORMANCE_METHODOLOGY.md for why they differ.'
    AS
    WITH bounds AS (
        SELECT client_id, client_name, MIN(as_of) AS inception_date, MAX(as_of) AS as_of
        FROM {SCHEMA}.gold_performance
        GROUP BY client_id, client_name
    ),
    endpoints AS (
        SELECT b.client_id, b.client_name, b.inception_date, b.as_of,
               v0.total_wealth_usd AS wealth_begin_usd,
               vn.total_wealth_usd AS wealth_end_usd,
               vn.twr_index_since_inception - 1 AS twr_since_inception
        FROM bounds b
        JOIN {SCHEMA}.gold_performance v0 ON v0.client_id = b.client_id AND v0.as_of = b.inception_date
        JOIN {SCHEMA}.gold_performance vn ON vn.client_id = b.client_id AND vn.as_of = b.as_of
    ),
    flows AS (
        -- Modified Dietz: each flow weighted by the fraction of the period
        -- it was invested — a flow on the last day carries weight 0, a flow
        -- on the first day (excluded here — already inside wealth_begin,
        -- same boundary rule as the chain above) would carry weight 1.
        SELECT p.client_id,
               SUM(p.external_flow_usd) AS net_flow_since_inception,
               SUM(p.external_flow_usd
                   * (DATEDIFF(e.as_of, p.as_of) / DATEDIFF(e.as_of, e.inception_date)))
                   AS dietz_weighted_flow
        FROM {SCHEMA}.gold_performance p
        JOIN endpoints e USING (client_id)
        WHERE p.as_of > e.inception_date
        GROUP BY p.client_id
    )
    SELECT
        e.client_id,
        e.client_name,
        e.inception_date,
        e.as_of,
        CAST(e.wealth_begin_usd AS DECIMAL(24,2))                        AS wealth_begin_usd,
        CAST(e.wealth_end_usd AS DECIMAL(24,2))                          AS wealth_end_usd,
        CAST(COALESCE(f.net_flow_since_inception, 0) AS DECIMAL(24,2))   AS net_external_flow_usd,
        CAST(e.twr_since_inception AS DECIMAL(14,8))                     AS twr_since_inception,
        CAST((e.wealth_end_usd - e.wealth_begin_usd - COALESCE(f.net_flow_since_inception, 0))
             / (e.wealth_begin_usd + COALESCE(f.dietz_weighted_flow, 0))
             AS DECIMAL(14,8))                                           AS dietz_since_inception,
        CAST(i.irr_str AS DECIMAL(14,8))                                 AS irr_since_inception_annualized,
        current_timestamp()                                              AS rebuilt_at
    FROM endpoints e
    LEFT JOIN flows f USING (client_id)
    LEFT JOIN irr_raw i USING (client_id)"""
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

# MAGIC %md ## `gold_ownership` — the ownership graph
# MAGIC
# MAGIC The account→client edges from `silver_account_owners`, projected as-is
# MAGIC with two derived columns: how many clients own each account, and whether
# MAGIC it is shared. This is structure, not money — the monetary attribution is
# MAGIC already prorated into wealth/allocation/holdings. It exists so the serving
# MAGIC layer can show *who owns what*, including the 60/40 shared account whose
# MAGIC two owners are why proration matters at all.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_ownership
    COMMENT 'The ownership graph: one row per (account, owning client) with the effective fraction, the number of owners on the account, and whether it is shared. Structural — fractions per account sum to 1.'
    AS
    WITH counted AS (
        SELECT account_id, client_id, client_name, ownership_pct,
               COUNT(*) OVER (PARTITION BY account_id) AS owner_count
        FROM {SCHEMA}.silver_account_owners
    )
    SELECT
        account_id,
        client_id,
        client_name,
        CAST(ownership_pct AS DECIMAL(9,6)) AS ownership_pct,
        CAST(owner_count AS INT)            AS owner_count,
        owner_count > 1                     AS is_shared,
        current_timestamp()                 AS rebuilt_at
    FROM counted"""
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
        "alts_usd": "Owner-prorated private-fund NAV in USD, forward-filled from the most recent confirmed capital account statement (see alts_daily, D-060); 0 before a client's first confirmed statement or if they hold no alts fund",
        "total_wealth_usd": "positions_usd + cash_usd + alts_usd — the headline number",
        "fx_rate_used": "EUR→USD ECB reference rate applied to this date's EUR amounts",
        "fx_rate_date": "The day fx_rate_used was published; earlier than as_of means carried forward (weekend/holiday) — labelled, not hidden",
        "books_reconcile": "TRUE when the DQ layer's conformed cash check passes for every account this client owns on this date",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_asset_allocation": {
        "as_of": "Valuation date. Grain: one row per (client, date, asset_class)",
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "asset_class": "Instrument class from the securities master; 'Cash' for cash; 'Alternatives' for owner-prorated, forward-filled alts NAV (D-060); 'Unknown' where the master could not identify the instrument (kept visible, D-022)",
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
    "gold_performance": {
        "as_of": "Valuation date. Grain: one row per (client, date)",
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "total_wealth_usd": "Same figure as gold_client_wealth.total_wealth_usd, carried for self-contained querying",
        "external_flow_usd": "Net client contribution (positive) or withdrawal (negative) in USD that day; 0 on days with no flow",
        "daily_twr_return": "(total_wealth_usd − external_flow_usd) / previous day's total_wealth_usd − 1; NULL on the client's first date (no prior day to compare)",
        "twr_index_since_inception": "Chain-linked growth-of-$1 index from the client's first date (1.0 there); > 1.0 means the market grew the account net of the client's own flows",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_performance_summary": {
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "inception_date": "The client's first date in gold_performance — the start of the since-inception window",
        "as_of": "The latest date in gold_performance — the end of the since-inception window",
        "wealth_begin_usd": "total_wealth_usd on inception_date",
        "wealth_end_usd": "total_wealth_usd on as_of",
        "net_external_flow_usd": "Sum of external_flow_usd strictly after inception_date (inception day's flow is already inside wealth_begin_usd)",
        "twr_since_inception": "Time-weighted return over the window: gold_performance's chained index minus 1. Not annualized (GIPS convention for sub-annual periods)",
        "dietz_since_inception": "Modified Dietz return over the same window: (end − begin − net flow) / (begin + day-weighted flow). Not annualized; tracks TWR closely when flows are small relative to wealth",
        "irr_since_inception_annualized": "Money-weighted return (XIRR) over the same cash flows, solved by bisection and reported ANNUALIZED (the standard IRR convention) — diverges from the two return-based figures above on a short period by construction, not by error. NULL when no root exists in [-99.99%, +1000%]",
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
    "gold_ownership": {
        "account_id": "Custodial account. Grain: one row per (account, owning client)",
        "client_id": "A client that owns some fraction of this account",
        "client_name": "Display name of the client",
        "ownership_pct": "This client's effective fraction of the account; fractions per account sum to 1",
        "owner_count": "How many clients own this account (2+ means a shared account)",
        "is_shared": "True when the account has more than one owner (owner_count > 1)",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_alts_holdings": {
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "fund_id": "Private-fund identifier (parvum_alts_hitl.generate.FUND_UNIVERSE)",
        "fund_name": "Display name of the fund",
        "account_id": "Custody account this fund's commitment rolls up to",
        "inception_date": "Earliest confirmed document date for this fund (call, distribution, or statement)",
        "as_of": "Period end of the latest confirmed capital account statement; NULL if none confirmed yet",
        "total_commitment_usd": "Owner-prorated total commitment, from the latest confirmed statement (or calls alone if no statement is confirmed yet)",
        "called_to_date_usd": "Owner-prorated cumulative capital called, from the latest confirmed capital call",
        "distributed_to_date_usd": "Owner-prorated cumulative capital distributed, from the latest confirmed distribution",
        "unfunded_commitment_usd": "Owner-prorated total_commitment_usd minus called_to_date_usd",
        "current_nav_usd": "Owner-prorated ending balance from the latest confirmed capital account statement; 0 if none confirmed yet",
        "moic": "(distributed_to_date_usd + current_nav_usd) / called_to_date_usd — multiple on invested capital, unprorated (a ratio is owner-invariant); NULL if nothing has been called yet",
        "pending_review_documents": "Count of this fund's documents still awaiting a human decision (routing = needs_review, reviewed_status NULL) — not reflected in any figure above",
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
        f"""SELECT client_name, total_wealth_usd, positions_usd, cash_usd, alts_usd,
               fx_rate_used, fx_rate_date, books_reconcile
        FROM {SCHEMA}.gold_client_wealth
        WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_client_wealth)
        ORDER BY total_wealth_usd DESC"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, fund_name, total_commitment_usd, called_to_date_usd,
               distributed_to_date_usd, unfunded_commitment_usd, current_nav_usd, moic,
               pending_review_documents
        FROM {SCHEMA}.gold_alts_holdings
        ORDER BY client_name, fund_name"""
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

# COMMAND ----------

# MAGIC %md ## Since inception, three ways

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, inception_date, as_of,
               wealth_begin_usd, wealth_end_usd, net_external_flow_usd,
               twr_since_inception, dietz_since_inception, irr_since_inception_annualized
        FROM {SCHEMA}.gold_performance_summary
        ORDER BY wealth_end_usd DESC"""
    )
)
