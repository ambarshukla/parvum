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

from pyspark.sql.types import StringType, StructField, StructType

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
# MAGIC
# MAGIC The range has to cover alts statement dates too (D-061), not just the
# MAGIC custodial feed's own window: the alts corpus's document history runs
# MAGIC back to 2024, well before the feed's much shorter, more recent window,
# MAGIC and a EUR-denominated fund needs a rate for every one of those earlier
# MAGIC dates to convert its NAV. `silver_alts_documents.period_end` alone is
# MAGIC enough — by construction (`parvum_alts_hitl.book`'s quarter indices)
# MAGIC every call/distribution date already falls within some statement's own
# MAGIC period-end range.

# COMMAND ----------

lo, hi = spark.sql(  # noqa: F821
    f"""SELECT MIN(d), MAX(d) FROM (
        SELECT as_of AS d FROM {SCHEMA}.silver_positions
        UNION ALL
        SELECT CAST(period_end AS DATE) AS d FROM {SCHEMA}.silver_alts_documents
        WHERE period_end IS NOT NULL
    )"""
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
# MAGIC **Currency-converted, not assumed USD (D-061).** The corpus now
# MAGIC includes a EUR-denominated fund, so every money figure below is
# MAGIC computed twice: once in the document's own (native) currency — what a
# MAGIC reviewer actually reads on the page — and once converted to USD via
# MAGIC the same `fx` view positions and cash already use, at the specific
# MAGIC date each figure is *as of* (a statement's own period end, or a fund's
# MAGIC earliest document date when no statement is confirmed yet). A ratio
# MAGIC like MOIC needs no conversion at all — numerator and denominator scale
# MAGIC by the same rate, so it cancels regardless of which currency it started in.

# COMMAND ----------

_alts_confirmed = spark.sql(  # noqa: F821
    f"""SELECT fund_id, currency, doc_type, confirmed_fields_json
    FROM {SCHEMA}.silver_alts_documents WHERE confirmed_fields_json IS NOT NULL"""
).collect()

_pending_docs_by_fund: dict[str, list] = {}
for _row in spark.sql(  # noqa: F821
    f"""SELECT fund_id, doc_type, period_end FROM {SCHEMA}.silver_alts_documents
    WHERE routing = 'needs_review' AND reviewed_status IS NULL"""
).collect():
    _pending_docs_by_fund.setdefault(_row.fund_id, []).append(_row)

_alts_pending = {fid: len(rows) for fid, rows in _pending_docs_by_fund.items()}
# The latest pending statement period lets the UI compare against `as_of` to
# show how far behind the confirmed NAV is -- how much staler the client's
# figure is, without exposing the internal doc-type taxonomy behind it.
_alts_pending_latest_period = {
    fid: max((date.fromisoformat(r.period_end) for r in rows if r.period_end), default=None)
    for fid, rows in _pending_docs_by_fund.items()
}

_calls: dict[str, list[dict]] = {}
_dists: dict[str, list[dict]] = {}
_stmts: dict[str, list[dict]] = {}
_by_doc_type = {"capital_call": _calls, "distribution": _dists, "capital_account_statement": _stmts}
_fund_currency: dict[str, str] = {}
for _row in _alts_confirmed:
    # fund_id is never a key inside the fields JSON itself -- it's a
    # directory-derived fact the extraction pipeline attaches alongside
    # `fields` (parvum_alts_hitl.extract.process_directory), not something
    # the LLM was asked to read off the page. Group by the silver row's own
    # column, never by parsing it back out of the JSON. Same story for
    # currency (D-061): it's extracted per-document but is a fund-level
    # constant, so the silver column -- reliable even for an undecided
    # needs_review row -- is the source of truth, not this JSON.
    _fields = json.loads(_row.confirmed_fields_json)
    _by_doc_type[_row.doc_type].setdefault(_row.fund_id, []).append(_fields)
    _fund_currency[_row.fund_id] = _row.currency

_alts_fund_rows = []
_alts_nav_rows = []
for _fid in sorted(set(_calls) | set(_dists) | set(_stmts)):
    _fund_calls = sorted(_calls.get(_fid, []), key=lambda f: f["call_number"])
    _fund_dists = sorted(_dists.get(_fid, []), key=lambda f: f["distribution_number"])
    _fund_stmts = sorted(_stmts.get(_fid, []), key=lambda f: f["period_end"])
    _any_doc = (_fund_stmts or _fund_calls or _fund_dists)[0]

    if _fund_stmts:
        # One document, one moment (D-072). Every term of MOIC comes from the
        # latest confirmed capital account statement, because that statement
        # reports the fund as it actually stands — it already embeds every call
        # the fund ever made, whether or not our review queue has processed the
        # matching call notice.
        #
        # Deriving `called` from the confirmed *call notices* instead mixes two
        # states of the world: a fully-loaded NAV over a partially-confirmed
        # denominator. It inflated MOIC to 4.1-4.65x, and made the multiple move
        # with review progress rather than fund performance — approving a
        # pending call would push MOIC *down*. It also left
        # called + unfunded != commitment, visible in gold and unnoticed.
        _latest = _fund_stmts[-1]
        _nav = parse_decimal(_latest["ending_balance"])
        _unfunded = parse_decimal(_latest["unfunded_commitment"])
        _commitment = parse_decimal(_latest["total_commitment"])
        _stmt_as_of = date.fromisoformat(_latest["period_end"])
        _called = _commitment - _unfunded

        # Distributions belong in the numerator, but only those that had already
        # left the fund by the NAV's own date. A distribution *after* the
        # statement reduces NAV in reality while our carried-forward NAV still
        # predates it, so adding it counts the same money twice.
        _dists_by_then = [
            f
            for f in _fund_dists
            if date.fromisoformat(f["distribution_date"]) <= _stmt_as_of
        ]
        _distributed = (
            parse_decimal(_dists_by_then[-1]["cumulative_distributed"])
            if _dists_by_then
            else Decimal(0)
        )
    else:
        # No confirmed statement yet — fall back to what the calls imply. Here
        # the notices are the only account of the fund that exists, so they are
        # the consistent source rather than a mismatched one.
        _called = parse_decimal(_fund_calls[-1]["cumulative_called"]) if _fund_calls else Decimal(0)
        _distributed = (
            parse_decimal(_fund_dists[-1]["cumulative_distributed"]) if _fund_dists else Decimal(0)
        )
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

    _inception = min(_dates) if _dates else None
    _currency = _fund_currency[_fid]
    _alts_fund_rows.append(
        {
            "fund_id": _fid,
            "fund_name": _any_doc["fund_name"],
            "account_id": _any_doc["account_id"],
            "currency": _currency,
            "inception_date": _inception,
            "as_of": _stmt_as_of,
            # Native-currency figures -- converted to USD in SQL below,
            # against the specific date each one is as of. Deliberately not
            # named *_usd here: that suffix is earned after conversion.
            "total_commitment_native": _commitment,
            "called_to_date_native": _called,
            "distributed_to_date_native": _distributed,
            "unfunded_commitment_native": _unfunded,
            "current_nav_native": _nav,
            "moic_str": str(_moic) if _moic is not None else None,
            "pending_review_documents": int(_alts_pending.get(_fid, 0)),
            "pending_review_latest_period": _alts_pending_latest_period.get(_fid),
        }
    )
    for _stmt in _fund_stmts:
        _alts_nav_rows.append(
            {
                "fund_id": _fid,
                "account_id": _any_doc["account_id"],
                "currency": _currency,
                "statement_date": date.fromisoformat(_stmt["period_end"]),
                "nav_native": parse_decimal(_stmt["ending_balance"]),
            }
        )

print(f"alts: {len(_alts_fund_rows)} funds, {len(_alts_nav_rows)} confirmed NAV marks")

# COMMAND ----------

spark.createDataFrame(  # noqa: F821
    _alts_fund_rows,
    schema="fund_id STRING, fund_name STRING, account_id STRING, currency STRING, "
    "inception_date DATE, as_of DATE, total_commitment_native DECIMAL(24,2), "
    "called_to_date_native DECIMAL(24,2), distributed_to_date_native DECIMAL(24,2), "
    "unfunded_commitment_native DECIMAL(24,2), current_nav_native DECIMAL(24,2), "
    "moic_str STRING, pending_review_documents INT, pending_review_latest_period DATE",
).createOrReplaceTempView("alts_fund_raw")

spark.createDataFrame(  # noqa: F821
    _alts_nav_rows,
    schema="fund_id STRING, account_id STRING, currency STRING, statement_date DATE, "
    "nav_native DECIMAL(24,2)",
).createOrReplaceTempView("alts_nav_raw")

# Owner-prorated NAV in USD per (client, FUND, statement date) — kept at
# fund grain, not summed across a client's funds yet. A client can hold more
# than one alts fund on different statement schedules (Okafor: Bramwell and
# Alpenrose), so collapsing to (client, date) here would let one fund's
# later statement silently push another fund's earlier-but-still-current
# mark out of the picture the moment alts_daily's forward fill looks at only
# the most recent date it has a row for. Converted at each statement's own
# date's rate (fx is keyed by as_of, so joined on statement_date here).
spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TEMP VIEW alts_nav_points AS
    SELECT o.client_id, n.fund_id, n.statement_date,
           CAST(
               (CASE WHEN n.currency = 'USD' THEN n.nav_native ELSE n.nav_native * f.eur_usd END)
               * o.ownership_pct
           AS DECIMAL(24,2)) AS nav_usd
    FROM alts_nav_raw n
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)
    JOIN fx f ON f.as_of = n.statement_date"""
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
    COMMENT 'Owner-prorated private-fund holdings, one row per (client, fund): commitment, capital called and distributed to date, unfunded commitment, current NAV, and MOIC, converted to USD at the rate for each figure''s own as-of date. Only confirmed (auto-accepted or human-reviewed) documents are reflected -- pending_review_documents/_latest_period describe what is deliberately left out.'
    AS
    WITH rated AS (
        -- One rate per fund: the latest confirmed statement's date, or (no
        -- statement confirmed yet) the fund's earliest document date.
        -- Native-currency figures stay native (no-op for USD, CASE WHEN
        -- below does the actual conversion) until multiplied out.
        SELECT f.*, COALESCE(fx1.eur_usd, fx2.eur_usd) AS eur_usd
        FROM alts_fund_raw f
        LEFT JOIN fx fx1 ON fx1.as_of = f.as_of
        LEFT JOIN fx fx2 ON fx2.as_of = f.inception_date
    )
    SELECT
        o.client_id,
        o.client_name,
        r.fund_id,
        r.fund_name,
        r.account_id,
        r.currency,
        r.inception_date,
        r.as_of,
        CAST((CASE WHEN r.currency = 'USD' THEN r.total_commitment_native
                   ELSE r.total_commitment_native * r.eur_usd END)
             * o.ownership_pct AS DECIMAL(24,2))                          AS total_commitment_usd,
        CAST((CASE WHEN r.currency = 'USD' THEN r.called_to_date_native
                   ELSE r.called_to_date_native * r.eur_usd END)
             * o.ownership_pct AS DECIMAL(24,2))                          AS called_to_date_usd,
        CAST((CASE WHEN r.currency = 'USD' THEN r.distributed_to_date_native
                   ELSE r.distributed_to_date_native * r.eur_usd END)
             * o.ownership_pct AS DECIMAL(24,2))                          AS distributed_to_date_usd,
        CAST((CASE WHEN r.currency = 'USD' THEN r.unfunded_commitment_native
                   ELSE r.unfunded_commitment_native * r.eur_usd END)
             * o.ownership_pct AS DECIMAL(24,2))                          AS unfunded_commitment_usd,
        CAST((CASE WHEN r.currency = 'USD' THEN r.current_nav_native
                   ELSE r.current_nav_native * r.eur_usd END)
             * o.ownership_pct AS DECIMAL(24,2))                          AS current_nav_usd,
        -- Owner-invariant ratio -- proration cancels, and so does currency
        -- (both sides of distributed+nav / called scale by the same rate).
        CAST(r.moic_str AS DECIMAL(14,6))                                  AS moic,
        r.pending_review_documents,
        r.pending_review_latest_period,
        current_timestamp()                                                AS rebuilt_at
    FROM rated r
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)"""
)

# COMMAND ----------

# MAGIC %md ### `alts_daily` — forward-filled NAV, one row per (client, date)
# MAGIC
# MAGIC Reused by both `gold_client_wealth` and `gold_asset_allocation` below.
# MAGIC Forward-filled *per fund first, summed second* — not the other way
# MAGIC round. A client holding more than one fund (Okafor: Bramwell and
# MAGIC Alpenrose) will see each fund report its own statements on its own
# MAGIC schedule; summing by date before filling would mean the moment either
# MAGIC fund's date range moves past the other's, the LAST_VALUE window picks
# MAGIC up only the most-recently-reporting fund's contribution and silently
# MAGIC drops the other's still-current mark. The date grid for each fund's
# MAGIC own fill is every date `silver_position_owners` already reports on,
# MAGIC UNIONed with that fund's own statement dates — a statement landing
# MAGIC *before* the wealth-reporting window even starts still has to seed the
# MAGIC forward fill, or its NAV would read as zero for the whole window
# MAGIC instead of "whatever the last confirmed mark said".

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TEMP VIEW alts_daily AS
    WITH wealth_dates AS (
        SELECT DISTINCT as_of, client_id, client_name FROM {SCHEMA}.silver_position_owners
    ),
    funds AS (
        SELECT DISTINCT client_id, fund_id FROM alts_nav_points
    ),
    all_dates AS (
        SELECT w.as_of, f.client_id, f.fund_id
        FROM wealth_dates w
        JOIN funds f USING (client_id)
        UNION
        SELECT statement_date AS as_of, client_id, fund_id FROM alts_nav_points
    ),
    joined AS (
        SELECT d.as_of, d.client_id, d.fund_id, p.nav_usd
        FROM all_dates d
        LEFT JOIN alts_nav_points p
            ON p.client_id = d.client_id AND p.fund_id = d.fund_id AND p.statement_date = d.as_of
    ),
    filled AS (
        SELECT as_of, client_id, fund_id,
               COALESCE(LAST_VALUE(nav_usd, true) OVER (
                   PARTITION BY client_id, fund_id ORDER BY as_of
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) AS nav_usd
        FROM joined
    ),
    summed AS (
        SELECT as_of, client_id, SUM(nav_usd) AS alts_usd
        FROM filled
        GROUP BY as_of, client_id
    )
    SELECT w.as_of, w.client_id, w.client_name, COALESCE(s.alts_usd, 0) AS alts_usd
    FROM wealth_dates w
    LEFT JOIN summed s ON s.as_of = w.as_of AND s.client_id = w.client_id"""
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
        UNION ALL
        SELECT currency FROM {SCHEMA}.silver_alts_documents WHERE currency IS NOT NULL
    ) WHERE ccy NOT IN ('USD', 'EUR')"""
).collect()
if unknown:
    raise ValueError(f"currencies gold cannot convert: {[r['ccy'] for r in unknown]}")

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_client_wealth
    COMMENT 'Per client per day: total wealth in USD (positions + closing cash + forward-filled alts NAV, converted at that day''s ECB reference rate). books_reconcile is the DQ layer''s cash verdict across the client''s accounts; reconcile_break_accounts/_variance_usd give the detail behind a FALSE.'
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
        -- the client's day unreconciled. Verdicts come from dq_cash_integrity;
        -- reconcile_break_accounts/_variance_usd are this client's prorated
        -- share of the broken accounts' own arithmetic gap (|delta_conformed|,
        -- converted to USD at the day's rate) -- so a FALSE verdict can say
        -- how many accounts and how much, not just yes/no.
        SELECT d.as_of, o.client_id,
               every(d.conformed_consistent)                                AS books_reconcile,
               SUM(CASE WHEN NOT d.conformed_consistent THEN 1 ELSE 0 END)  AS reconcile_break_accounts,
               SUM(CASE WHEN NOT d.conformed_consistent
                        THEN ABS(d.delta_conformed)
                             * (CASE WHEN d.currency = 'USD' THEN 1 ELSE f.eur_usd END)
                             * o.ownership_pct
                        ELSE 0 END)                                         AS reconcile_variance_usd
        FROM {SCHEMA}.dq_cash_integrity d
        JOIN {SCHEMA}.silver_account_owners o USING (account_id)
        JOIN fx f USING (as_of)
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
        COALESCE(q.reconcile_break_accounts, 0)                      AS reconcile_break_accounts,
        CAST(COALESCE(q.reconcile_variance_usd, 0) AS DECIMAL(24,2)) AS reconcile_variance_usd,
        current_timestamp()                                          AS rebuilt_at
    FROM pos p
    LEFT JOIN cash c     USING (as_of, client_id)
    LEFT JOIN alts_daily a USING (as_of, client_id)
    LEFT JOIN quality q USING (as_of, client_id)
    JOIN fx f USING (as_of)"""
)

# COMMAND ----------

# MAGIC %md ## `gold_reconciliation_exceptions` — the accounts behind a FALSE
# MAGIC
# MAGIC Grain: one row per (client, account) currently failing the conformed
# MAGIC cash check, on the same latest date `gold_client_wealth`'s badge
# MAGIC reflects — like `gold_top_holdings`, "latest date only" is baked in
# MAGIC here rather than filtered at query time, so a client with a clean day
# MAGIC simply has no rows. `reconcile_break_accounts`/`_variance_usd` on
# MAGIC `gold_client_wealth` answer "how many, how much"; this answers "which
# MAGIC ones" -- the drill-down the aggregate alone can't provide. The delta
# MAGIC is signed (unlike the aggregate's `ABS`, which has to be unsigned
# MAGIC because summing signed gaps across accounts would let them cancel out
# MAGIC nonsensically) -- a single account's own gap direction is real
# MAGIC information once you're looking at just that account.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.gold_reconciliation_exceptions
    COMMENT 'Per client per currently-broken account: this client''s prorated share of the account''s conformed-cash arithmetic gap (opening + movements vs. closing), signed, in both the account''s native currency and USD. Latest date only, like gold_top_holdings -- a client with reconcile_break_accounts = 0 has no rows here.'
    AS
    SELECT
        o.client_id,
        o.client_name,
        d.account_id,
        d.as_of,
        d.currency,
        CAST(d.delta_conformed * o.ownership_pct AS DECIMAL(24,2)) AS delta_native,
        CAST(d.delta_conformed * o.ownership_pct
             * (CASE WHEN d.currency = 'USD' THEN 1 ELSE f.eur_usd END)
             AS DECIMAL(24,2))                                     AS delta_usd,
        current_timestamp()                                        AS rebuilt_at
    FROM {SCHEMA}.dq_cash_integrity d
    JOIN {SCHEMA}.silver_account_owners o USING (account_id)
    JOIN fx f USING (as_of)
    WHERE d.as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_client_wealth)
      AND NOT d.conformed_consistent"""
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

# MAGIC %md ## Declared book restatements — value changes that are not returns
# MAGIC
# MAGIC Every account here is a scale model of a real 13F filer: the filer's
# MAGIC share counts divided by that account's `share_divisor`. The divisor is a
# MAGIC modelling parameter, not a market fact, so when it changes the account's
# MAGIC wealth changes with it — same holdings, same prices, a different ruler.
# MAGIC
# MAGIC A return chain cannot see the difference. It reads yesterday's wealth,
# MAGIC today's wealth and no cash flow between them, and concludes the manager
# MAGIC earned the gap. On 2026-08-17 that produced a **+414% one-day return**
# MAGIC on a book that had earned nothing (D-066 rescaled both Berkshire
# MAGIC divisors fivefold so a new 3,564-share position would not round to
# MAGIC zero). Arithmetically correct, completely false — and the third time
# MAGIC this project has met the same bug class: D-016 fixed restatement
# MAGIC handling at bronze, D-018 found it again at the file-arrival trigger,
# MAGIC and here it is a third time at gold. Fixing a bug class at one layer
# MAGIC still says nothing about the others.
# MAGIC
# MAGIC **Declared, never inferred.** "Any suspiciously large move is a
# MAGIC restatement" would also swallow the legitimate quarterly step a new 13F
# MAGIC filing regime produces — a real return arriving all at once, not a fake
# MAGIC one (2026-05-15 moved all three clients 4–6% on zero flow, and that one
# MAGIC is genuine). The two are identical in shape and opposite in meaning, so
# MAGIC only the book can say which is which. `parvum_reference.restatements`
# MAGIC is where it says so, landed here on the same pull-not-push contract as
# MAGIC the FX rates and the CDE register (D-006, D-070).
# MAGIC
# MAGIC Reading it is deliberately strict: a missing snapshot fails the job
# MAGIC rather than defaulting to "nothing was ever restated", because that
# MAGIC default is precisely the wrong number wearing a confident face.

# COMMAND ----------

RESTATEMENTS_PATH = "/Volumes/workspace/parvum/landing/reference/book_restatements.json"

# Explicit rather than inferred, for the same reason the CDE register's schema
# is: the landed file is a contract, and divisors travel as strings so no JSON
# float can round one into something that no longer reconciles to accounts.py.
RESTATEMENT_SCHEMA = StructType(
    [
        StructField("effective_date", StringType(), nullable=False),
        StructField("account_id", StringType(), nullable=False),
        StructField("divisor_before", StringType(), nullable=False),
        StructField("divisor_after", StringType(), nullable=False),
        StructField("reason", StringType(), nullable=False),
        StructField("decision_ref", StringType(), nullable=False),
    ]
)

spark.read.schema(RESTATEMENT_SCHEMA).json(RESTATEMENTS_PATH).createOrReplaceTempView(  # noqa: F821
    "book_restatements_raw"
)
spark.sql(  # noqa: F821
    """CREATE OR REPLACE TEMP VIEW book_restatements AS
    SELECT CAST(effective_date AS DATE) AS effective_date, account_id,
           CAST(divisor_before AS DECIMAL(18,4)) AS divisor_before,
           CAST(divisor_after AS DECIMAL(18,4)) AS divisor_after,
           reason, decision_ref
    FROM book_restatements_raw"""
)
print(
    f"book restatements declared: {spark.sql('SELECT COUNT(*) c FROM book_restatements').first().c}"  # noqa: F821
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
# MAGIC
# MAGIC **A declared restatement breaks the chain rather than entering it.** On
# MAGIC such a day `daily_twr_return` is NULL for exactly the same reason it is
# MAGIC NULL at inception — there is no comparable prior day, because the two
# MAGIC days are denominated in different rulers — and the index links straight
# MAGIC through, unchanged. The whole non-flow move is booked to
# MAGIC `restatement_adjustment_usd` instead, and `restatement_detail` names the
# MAGIC account, the divisors and the decision behind it, so the step is
# MAGIC explainable from the row rather than only from a commit message.
# MAGIC
# MAGIC Booking the *entire* non-flow change to the restatement forfeits
# MAGIC whatever genuine market return also happened that day (2026-08-17 was
# MAGIC also a filing-regime boundary, so some of that step was real — Okafor,
# MAGIC unaffected by the divisor change, moved +2.1%). That is the deliberate
# MAGIC trade: on a restated day the honest options are "measure nothing" or
# MAGIC "guess at a split", and a performance figure is the wrong place to
# MAGIC guess. Real books treat a restated period the same way — excluded and
# MAGIC disclosed, not partially credited.

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
    restated_clients AS (
        -- Restatements are declared per account because that is where a
        -- divisor lives; performance is measured per client, so a declaration
        -- reaches every client with a stake in the restated account.
        SELECT r.effective_date AS as_of, o.client_id,
               CONCAT_WS(' | ', SORT_ARRAY(COLLECT_SET(
                   CONCAT(r.account_id, ': divisor ',
                          CAST(CAST(r.divisor_before AS DECIMAL(18,0)) AS STRING), ' -> ',
                          CAST(CAST(r.divisor_after AS DECIMAL(18,0)) AS STRING),
                          ' (', r.decision_ref, ')')))) AS restatement_detail
        FROM book_restatements r
        JOIN {SCHEMA}.silver_account_owners o ON o.account_id = r.account_id
        GROUP BY r.effective_date, o.client_id
    ),
    joined AS (
        SELECT w.as_of, w.client_id, w.client_name, w.total_wealth_usd,
               COALESCE(fl.flow_usd, 0) AS external_flow_usd,
               rc.restatement_detail,
               LAG(w.total_wealth_usd) OVER (
                   PARTITION BY w.client_id ORDER BY w.as_of) AS prev_wealth_usd
        FROM {SCHEMA}.gold_client_wealth w
        LEFT JOIN flows fl USING (as_of, client_id)
        LEFT JOIN restated_clients rc USING (as_of, client_id)
    ),
    returns AS (
        SELECT *,
               -- The whole non-flow move on a declared restatement day is the
               -- restatement's, not the market's. Zero on every other day, so
               -- the column is safe to sum blindly downstream.
               CASE WHEN prev_wealth_usd IS NULL THEN 0
                    WHEN restatement_detail IS NULL THEN 0
                    ELSE total_wealth_usd - prev_wealth_usd - external_flow_usd
               END AS restatement_adjustment_usd,
               -- NULL on a restatement day for the same reason as at
               -- inception: no comparable prior day. The index's COALESCE
               -- below then links straight through it.
               CASE WHEN prev_wealth_usd IS NULL THEN NULL
                    WHEN restatement_detail IS NOT NULL THEN NULL
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
        CAST(restatement_adjustment_usd AS DECIMAL(24,2))              AS restatement_adjustment_usd,
        restatement_detail,
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


_perf_rows = spark.sql(  # noqa: F821
    f"SELECT as_of, client_id, total_wealth_usd, external_flow_usd, "
    f"restatement_adjustment_usd "
    f"FROM {SCHEMA}.gold_performance ORDER BY client_id, as_of"
).collect()
_by_client: dict[str, list] = {}
for _row in _perf_rows:
    _by_client.setdefault(_row.client_id, []).append(
        (_row.as_of, _row.total_wealth_usd, _row.external_flow_usd, _row.restatement_adjustment_usd)
    )

_irr_rows = []
for _client_id, _series in _by_client.items():
    _d0, _v0, _, _ = _series[0]
    _dn, _vn, _, _ = _series[-1]
    # The inception day's own flow is already reflected in v0 (a statement
    # balance is always ex-flow, i.e. after that day's activity settled), so
    # it must not also appear as a separate investor cash flow — the same
    # boundary convention gold_performance's daily chain uses (its first
    # daily_twr_return is NULL for the identical reason).
    _cfs: list[tuple] = [(_d0, -float(_v0))]
    for _d, _, _flow, _restatement in _series[1:]:
        # A restatement enters the series exactly where a contribution does,
        # and for the same arithmetic reason: it is value that appeared in the
        # account without the market putting it there, so IRR must not pay the
        # manager for it. It is reported on its own column rather than folded
        # into net flow because it is emphatically not the client's money.
        _non_market = float(_flow) + float(_restatement)
        if _non_market != 0:
            _cfs.append((_d, -_non_market))
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
        --
        -- A restatement is weighted identically, because in this formula it
        -- plays an identical role: value that entered the account without the
        -- market's help has to leave the numerator, or the return absorbs it.
        -- It is summed separately so the disclosure survives to the report.
        SELECT p.client_id,
               SUM(p.external_flow_usd) AS net_flow_since_inception,
               SUM(p.restatement_adjustment_usd) AS net_restatement_since_inception,
               SUM(p.external_flow_usd
                   * (DATEDIFF(e.as_of, p.as_of) / DATEDIFF(e.as_of, e.inception_date)))
                   AS dietz_weighted_flow,
               SUM(p.restatement_adjustment_usd
                   * (DATEDIFF(e.as_of, p.as_of) / DATEDIFF(e.as_of, e.inception_date)))
                   AS dietz_weighted_restatement
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
        CAST(COALESCE(f.net_restatement_since_inception, 0) AS DECIMAL(24,2))
                                                                         AS restatement_adjustment_usd,
        CAST(e.twr_since_inception AS DECIMAL(14,8))                     AS twr_since_inception,
        CAST((e.wealth_end_usd - e.wealth_begin_usd - COALESCE(f.net_flow_since_inception, 0)
              - COALESCE(f.net_restatement_since_inception, 0))
             / (e.wealth_begin_usd + COALESCE(f.dietz_weighted_flow, 0)
                + COALESCE(f.dietz_weighted_restatement, 0))
             AS DECIMAL(14,8))                                           AS dietz_since_inception,
        CAST(i.irr_str AS DECIMAL(14,8))                                 AS irr_since_inception_annualized,
        current_timestamp()                                              AS rebuilt_at
    FROM endpoints e
    LEFT JOIN flows f USING (client_id)
    LEFT JOIN irr_raw i USING (client_id)"""
)

# COMMAND ----------

# MAGIC %md ## `dq_return_plausibility` — the half that does not trust the register
# MAGIC
# MAGIC A declaration mechanism on its own is a licence: anything inconvenient
# MAGIC can be labelled a restatement after the fact, and nothing argues back.
# MAGIC So the declaration is only one side of this control. This table is the
# MAGIC other, and it deliberately does not consult the register when deciding
# MAGIC what looks wrong — only when deciding whether someone already owned it.
# MAGIC
# MAGIC For every client-day with a prior day it recomputes the raw non-flow
# MAGIC move, `(wealth − prev_wealth − flow) / prev_wealth`, and asks whether it
# MAGIC sits inside a stated band. Outside the band **and** undeclared is an
# MAGIC exception: a divisor changed in `accounts.py` with no matching entry in
# MAGIC `parvum_reference.restatements` surfaces here as a break instead of
# MAGIC reaching the client dashboard dressed as performance.
# MAGIC
# MAGIC Note what this is *not*. Recomputing the returns independently — the
# MAGIC obvious reading of the control gap the CDE register recorded against
# MAGIC these columns — would not have caught 2026-08-17 at all: the formula
# MAGIC was never wrong, so a second implementation reproduces +414.123%
# MAGIC faithfully. What failed was the *meaning* of an input, and only a
# MAGIC plausibility bound catches that. The register named the right area and
# MAGIC the wrong remedy, which is worth saying out loud (D-070) rather than
# MAGIC quietly closing the gap and claiming a prediction.
# MAGIC
# MAGIC **The band is 25%, and it is a judgement.** The largest legitimate
# MAGIC one-day move this book has ever produced is 5.8% — a quarterly 13F
# MAGIC filing regime landing a whole quarter of movement on one date, which is
# MAGIC real return, not an artefact, and must not trip the check. 25% clears
# MAGIC that with room for a genuinely violent quarter while still catching a
# MAGIC structural break, which arrives one to three orders of magnitude out
# MAGIC (+414%), never at 26%. A tighter band would be a daily false alarm; a
# MAGIC looser one would have let this through.

# COMMAND ----------

# Wide on purpose: this is a bound on the absurd, not a market-risk limit.
PLAUSIBILITY_BAND = 0.25

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.dq_return_plausibility
    COMMENT 'Per client per day: does the day-over-day wealth move, net of external flows, sit inside the stated plausibility band -- and if not, is there a declared book restatement that accounts for it? An implausible, undeclared move is a break. Computed from the raw wealth series rather than from daily_twr_return, so a restatement cannot hide inside its own NULL.'
    AS
    WITH moves AS (
        SELECT as_of, client_id, client_name, total_wealth_usd, external_flow_usd,
               restatement_detail,
               LAG(total_wealth_usd) OVER (
                   PARTITION BY client_id ORDER BY as_of) AS prev_wealth_usd
        FROM {SCHEMA}.gold_performance
    )
    SELECT
        as_of,
        client_id,
        client_name,
        CAST(total_wealth_usd AS DECIMAL(24,2))   AS total_wealth_usd,
        CAST(prev_wealth_usd AS DECIMAL(24,2))    AS prev_wealth_usd,
        CAST(external_flow_usd AS DECIMAL(24,2))  AS external_flow_usd,
        CAST((total_wealth_usd - prev_wealth_usd - external_flow_usd)
             / NULLIF(prev_wealth_usd, 0) AS DECIMAL(14,8)) AS non_flow_move_rate,
        {PLAUSIBILITY_BAND}                       AS band,
        restatement_detail IS NOT NULL            AS restatement_declared,
        restatement_detail,
        -- Declared or small enough: plausible. NULL on a client's first date,
        -- where there is nothing to compare -- the same convention
        -- dq_cash_continuity uses, so "no prior day" never reads as "clean".
        CASE WHEN prev_wealth_usd IS NULL THEN NULL
             WHEN restatement_detail IS NOT NULL THEN TRUE
             ELSE ABS((total_wealth_usd - prev_wealth_usd - external_flow_usd)
                      / NULLIF(prev_wealth_usd, 0)) <= {PLAUSIBILITY_BAND}
        END                                       AS plausible,
        current_timestamp()                       AS rebuilt_at
    FROM moves"""
)

# COMMAND ----------

# MAGIC %md ## Feeding the plausibility check back into `dq_metrics`
# MAGIC
# MAGIC `dq_metrics` is built in `dq_recon`, which runs *before* this job — so a
# MAGIC metric derived from gold cannot be computed there without reading the
# MAGIC previous run's numbers and reporting them as today's. Rather than add a
# MAGIC sixth task to the bundle for two rows, gold appends the rows it alone
# MAGIC can compute (D-070). The `DELETE` first makes the cell idempotent: gold
# MAGIC re-run on its own must not double-count.
# MAGIC
# MAGIC This is what closes the register's control gap on the performance
# MAGIC columns: a wrong return figure now moves a number a person watches,
# MAGIC instead of waiting for someone to notice a chart looked odd.

# COMMAND ----------

_PLAUSIBILITY_METRICS = ("daily_return_plausibility_rate", "return_plausibility_breaks_count")

spark.sql(  # noqa: F821
    f"""DELETE FROM {SCHEMA}.dq_metrics
    WHERE metric IN {_PLAUSIBILITY_METRICS}"""
)

spark.sql(  # noqa: F821
    f"""INSERT INTO {SCHEMA}.dq_metrics
    WITH counts AS (
        SELECT as_of, COUNT(*) AS checked,
               SUM(CASE WHEN plausible THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN plausible = FALSE THEN 1 ELSE 0 END) AS breaks
        FROM {SCHEMA}.dq_return_plausibility
        WHERE plausible IS NOT NULL
        GROUP BY as_of
    )
    SELECT as_of, 'accuracy' AS dimension, 'daily_return_plausibility_rate' AS metric,
           CAST(ok / NULLIF(checked, 0) AS DECIMAL(14,6)) AS value,
           breaks = 0 AS passed,
           CONCAT(CAST(ok AS STRING), ' of ', CAST(checked AS STRING),
                  ' client-days moved plausibly or were declared restatements') AS detail,
           current_timestamp() AS rebuilt_at
    FROM counts
    UNION ALL
    SELECT as_of, 'exceptions' AS dimension, 'return_plausibility_breaks_count' AS metric,
           CAST(breaks AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
           CONCAT(CAST(breaks AS STRING),
                  ' client-days moved implausibly with no declared restatement') AS detail,
           current_timestamp() AS rebuilt_at
    FROM counts"""
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
        "reconcile_break_accounts": "Count of this client's accounts where the conformed cash check fails on this date; 0 when books_reconcile is TRUE",
        "reconcile_variance_usd": "This client's prorated share of the broken accounts' own arithmetic gap (opening + movements vs. closing), summed in USD; 0 when books_reconcile is TRUE",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "gold_reconciliation_exceptions": {
        "client_id": "The family/relationship this row belongs to",
        "client_name": "Display name of the client",
        "account_id": "The specific account failing the conformed cash check — the detail gold_client_wealth.reconcile_break_accounts can only count",
        "as_of": "The date this exception is on — always the same latest date gold_client_wealth's badge reflects",
        "currency": "ISO 4217 currency code the account's own ledger is denominated in",
        "delta_native": "This client's prorated share of the account's arithmetic gap (opening + movements vs. closing) in the account's own currency, signed",
        "delta_usd": "Same figure converted to USD at the day's rate, signed",
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
        "restatement_adjustment_usd": "Value change on a declared book-restatement day that the market did not produce — the day's whole non-flow move, booked here instead of to return. 0 on every other day, so the column is safe to sum",
        "restatement_detail": "Which account was restated, from which divisor to which, and the decision that authorised it; NULL on days with no declared restatement",
        "daily_twr_return": "(total_wealth_usd − external_flow_usd) / previous day's total_wealth_usd − 1; NULL on the client's first date (no prior day to compare) and on a declared restatement day (the two days are denominated in different rulers, so there is no comparable prior day either)",
        "twr_index_since_inception": "Chain-linked growth-of-$1 index from the client's first date (1.0 there); > 1.0 means the market grew the account net of the client's own flows. Links straight through a restatement day rather than compounding it",
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
        "restatement_adjustment_usd": "Sum of restatement_adjustment_usd over the window — total value change from declared book restatements, removed from all three return figures and disclosed separately because it is not the client's money and not the market's doing",
        "twr_since_inception": "Time-weighted return over the window: gold_performance's chained index minus 1. Not annualized (GIPS convention for sub-annual periods)",
        "dietz_since_inception": "Modified Dietz return over the same window: (end − begin − net flow − restatement adjustment) / (begin + day-weighted flow + day-weighted restatement). Not annualized; tracks TWR closely when flows are small relative to wealth",
        "irr_since_inception_annualized": "Money-weighted return (XIRR) over the same cash flows, solved by bisection and reported ANNUALIZED (the standard IRR convention) — diverges from the two return-based figures above on a short period by construction, not by error. NULL when no root exists in [-99.99%, +1000%]",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "dq_return_plausibility": {
        "as_of": "Valuation date being checked. Grain: one row per (client, date)",
        "client_id": "The family/relationship whose wealth series is being checked",
        "client_name": "Display name of the client",
        "total_wealth_usd": "This day's total wealth in USD",
        "prev_wealth_usd": "The previous day's total wealth in USD; NULL on the client's first date",
        "external_flow_usd": "Net client contribution or withdrawal that day, removed before judging the move",
        "non_flow_move_rate": "(total_wealth_usd − prev_wealth_usd − external_flow_usd) / prev_wealth_usd — the day's move with the client's own money taken out. Computed from the raw wealth series, not from daily_twr_return, so a restatement cannot hide inside its own NULL",
        "band": "The plausibility bound in force (0.25). A judgement, not a market-risk limit: wide enough that a real quarterly filing regime step never trips it, tight enough that a structural break always does",
        "restatement_declared": "TRUE when a book restatement was declared for this client-day in parvum_reference.restatements",
        "restatement_detail": "The declaration that accounts for the move, when there is one; NULL otherwise",
        "plausible": "TRUE when the move is inside the band or a declared restatement explains it; FALSE means an implausible, undeclared move — a wrong number, not a bad day; NULL on the client's first date (nothing to compare)",
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
        "currency": "ISO 4217 currency code the fund's own documents are denominated in -- the *_usd columns are converted from this, not assumed already USD (D-061)",
        "inception_date": "Earliest confirmed document date for this fund (call, distribution, or statement)",
        "as_of": "Period end of the latest confirmed capital account statement; NULL if none confirmed yet",
        "total_commitment_usd": "Owner-prorated total commitment in USD, converted at the rate for as_of (or inception_date if no statement is confirmed yet)",
        "called_to_date_usd": "Owner-prorated cumulative capital called in USD, converted the same way. Derived from the latest confirmed capital account statement as total_commitment - unfunded_commitment, NOT by summing confirmed call notices — the statement reports the fund as it stands, so this counts every call the fund made rather than only the notices a reviewer has processed (D-072). Falls back to the notices only when no statement is confirmed yet",
        "distributed_to_date_usd": "Owner-prorated cumulative capital distributed in USD, converted the same way. Counts only distributions dated on or before the statement's period_end: a distribution after the NAV snapshot has not yet been deducted from that NAV, so including it would count the same money twice (D-072)",
        "unfunded_commitment_usd": "Owner-prorated (total_commitment - called_to_date) in USD, converted the same way",
        "current_nav_usd": "Owner-prorated ending balance from the latest confirmed capital account statement, in USD; 0 if none confirmed yet",
        "moic": "(distributed_to_date_usd + current_nav_usd) / called_to_date_usd — multiple on invested capital, unprorated (a ratio is owner-invariant); NULL if nothing has been called yet. Every term comes from the same confirmed statement and the same moment (D-072), so the multiple moves with fund performance rather than with how much of the review queue has been worked through",
        "pending_review_documents": "Count of this fund's documents still awaiting a human decision (routing = needs_review, reviewed_status NULL) — not reflected in any figure above",
        "pending_review_latest_period": "Latest period_end among pending capital_account_statement documents; NULL if no statement is pending. Compare against as_of to see how far behind the confirmed NAV is",
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
               fx_rate_used, fx_rate_date, books_reconcile, reconcile_break_accounts,
               reconcile_variance_usd
        FROM {SCHEMA}.gold_client_wealth
        WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_client_wealth)
        ORDER BY total_wealth_usd DESC"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, account_id, as_of, currency, delta_native, delta_usd
        FROM {SCHEMA}.gold_reconciliation_exceptions
        ORDER BY client_name, account_id"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT client_name, fund_name, total_commitment_usd, called_to_date_usd,
               distributed_to_date_usd, unfunded_commitment_usd, current_nav_usd, moic,
               pending_review_documents, pending_review_latest_period
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
