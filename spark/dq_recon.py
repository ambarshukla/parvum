# Databricks notebook source
# MAGIC %md
# MAGIC # Data quality — cross-format reconciliation and cash integrity
# MAGIC
# MAGIC The custodian tells us everything twice (holdings in semt.002 *and*
# MAGIC MT535) and gives cash an internal invariant (opening + movements =
# MAGIC closing). This notebook cashes both promises in: every disagreement
# MAGIC between the two holdings copies becomes a *finding* row, and every
# MAGIC account-day's cash is checked against its own arithmetic — raw and
# MAGIC conformed separately, because the difference between those two
# MAGIC verdicts is the proof that silver's cleaning was right.
# MAGIC
# MAGIC Principles:
# MAGIC - **Findings are rows, not logs.** A discrepancy is data with lineage,
# MAGIC   queryable and countable, not a warning that scrolled away.
# MAGIC - **Compare only what both sides actually say.** semt.002 never
# MAGIC   carries cost basis, so comparing it would manufacture 7,465 fake
# MAGIC   findings. Excluded, and the exclusion is documented — a check that
# MAGIC   cries wolf is worse than no check.
# MAGIC - **Full rebuild**, like all of silver: a pure function of bronze ×
# MAGIC   silver, restatement-proof by construction.

# COMMAND ----------

# MAGIC %md ## `dq_holdings_recon` — where the two copies disagree
# MAGIC
# MAGIC Grain: one row per finding. `MISSING_IN_*` = the position exists in
# MAGIC one format only (a mistyped identifier splits a pair into two of
# MAGIC these — one per side). `FIELD_MISMATCH` = both copies exist and a
# MAGIC field differs (null-safe: a value vs NULL is a difference).

# COMMAND ----------

from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType

SCHEMA = "workspace.parvum"

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.dq_holdings_recon
    COMMENT 'Cross-format reconciliation findings: one row per disagreement between the semt.002 and MT535 copies of a position. cost_basis is not compared (structurally absent from semt.002).'
    AS
    WITH semt AS (
        SELECT * FROM {SCHEMA}.bronze_holdings WHERE source_format = 'semt.002'
    ),
    mt AS (
        SELECT * FROM {SCHEMA}.bronze_holdings WHERE source_format = 'MT535'
    ),
    joined AS (
        SELECT
            COALESCE(s.as_of, m.as_of)                     AS as_of,
            COALESCE(s.account_id, m.account_id)           AS account_id,
            COALESCE(s.security_scheme, m.security_scheme) AS security_scheme,
            COALESCE(s.security_id, m.security_id)         AS security_id,
            s.file_path IS NOT NULL                        AS in_semt,
            m.file_path IS NOT NULL                        AS in_mt,
            s.security_name  AS s_name,  m.security_name  AS m_name,
            s.quantity       AS s_qty,   m.quantity       AS m_qty,
            s.price_amount   AS s_price, m.price_amount   AS m_price,
            s.price_as_of    AS s_pdate, m.price_as_of    AS m_pdate,
            s.market_value   AS s_mv,    m.market_value   AS m_mv
        FROM semt s
        FULL OUTER JOIN mt m
            ON s.as_of = m.as_of AND s.account_id = m.account_id
           AND s.security_scheme = m.security_scheme AND s.security_id = m.security_id
    )
    SELECT as_of, account_id, security_scheme, security_id,
           'MISSING_IN_MT535' AS finding, 'presence' AS field,
           'PRESENT' AS semt002_value, 'ABSENT' AS mt535_value,
           current_timestamp() AS rebuilt_at
    FROM joined WHERE in_semt AND NOT in_mt
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'MISSING_IN_SEMT002', 'presence', 'ABSENT', 'PRESENT', current_timestamp()
    FROM joined WHERE in_mt AND NOT in_semt
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'FIELD_MISMATCH', 'security_name', s_name, m_name, current_timestamp()
    FROM joined WHERE in_semt AND in_mt AND NOT (s_name <=> m_name)
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'FIELD_MISMATCH', 'quantity', CAST(s_qty AS STRING), CAST(m_qty AS STRING),
           current_timestamp()
    FROM joined WHERE in_semt AND in_mt AND NOT (s_qty <=> m_qty)
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'FIELD_MISMATCH', 'price_amount', CAST(s_price AS STRING), CAST(m_price AS STRING),
           current_timestamp()
    FROM joined WHERE in_semt AND in_mt AND NOT (s_price <=> m_price)
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'FIELD_MISMATCH', 'price_as_of', CAST(s_pdate AS STRING), CAST(m_pdate AS STRING),
           current_timestamp()
    FROM joined WHERE in_semt AND in_mt AND NOT (s_pdate <=> m_pdate)
    UNION ALL
    SELECT as_of, account_id, security_scheme, security_id,
           'FIELD_MISMATCH', 'market_value', CAST(s_mv AS STRING), CAST(m_mv AS STRING),
           current_timestamp()
    FROM joined WHERE in_semt AND in_mt AND NOT (s_mv <=> m_mv)"""
)

# COMMAND ----------

# MAGIC %md ## `dq_cash_integrity` — does each account-day's cash add up?
# MAGIC
# MAGIC The camt.053 invariant: opening + sum(movements) = closing. Checked
# MAGIC twice per account-day: against the **raw** bronze rows (duplicates and
# MAGIC all — is the custodian's file internally consistent?) and against the
# MAGIC **conformed** silver rows (after the duplicate collapse — is *our*
# MAGIC cleaned view consistent?). Raw breaks where the feed duplicated or
# MAGIC dropped; conformed breaks only where a movement is genuinely missing.
# MAGIC A day that breaks raw but passes conformed is the collapse proven
# MAGIC correct, row by row.
# MAGIC
# MAGIC **Amounts are stored unsigned; direction lives in the type** (camt.053
# MAGIC carries `CdtDbtInd` separately from the amount, and the parser keeps
# MAGIC that split). The debit set below mirrors `DEBIT_TYPES` in
# MAGIC `parvum_ingest/formats/camt053.py` — the renderer's own authority on
# MAGIC which types are debits. The first draft of this check summed raw
# MAGIC amounts and "found" all 325 account-days broken; a 100% failure rate
# MAGIC means the check is wrong, not the data.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.dq_cash_integrity
    COMMENT 'Per account-day cash invariant check: opening + movements = closing, evaluated against raw bronze and conformed silver separately. A raw break with a conformed pass validates the duplicate collapse; a conformed break means a movement is missing from the feed.'
    AS
    WITH bal AS (
        SELECT as_of, account_id,
               MAX(CASE WHEN balance_type = 'OPENING' THEN amount END) AS opening,
               MAX(CASE WHEN balance_type = 'CLOSING' THEN amount END) AS closing,
               MAX(currency) AS currency
        FROM {SCHEMA}.silver_cash_balances
        GROUP BY as_of, account_id
    ),
    raw_mov AS (
        SELECT as_of, account_id,
               SUM(CASE WHEN type IN ('BUY', 'FEE', 'TRANSFER_OUT')
                        THEN -amount ELSE amount END) AS movements_raw
        FROM {SCHEMA}.bronze_cash_entries
        GROUP BY as_of, account_id
    ),
    conf_mov AS (
        -- silver already applies the direction (signed_amount); only the raw
        -- side needs the CASE, because bronze is as-received by definition.
        SELECT as_of, account_id, SUM(signed_amount) AS movements_conformed
        FROM {SCHEMA}.silver_cash_transactions
        GROUP BY as_of, account_id
    )
    SELECT
        b.as_of,
        b.account_id,
        b.opening,
        b.closing,
        COALESCE(r.movements_raw, 0)        AS movements_raw,
        COALESCE(c.movements_conformed, 0)  AS movements_conformed,
        CAST(b.opening + COALESCE(r.movements_raw, 0) - b.closing
             AS DECIMAL(24,2))              AS delta_raw,
        CAST(b.opening + COALESCE(c.movements_conformed, 0) - b.closing
             AS DECIMAL(24,2))              AS delta_conformed,
        (b.opening + COALESCE(r.movements_raw, 0) = b.closing)       AS raw_consistent,
        (b.opening + COALESCE(c.movements_conformed, 0) = b.closing) AS conformed_consistent,
        b.currency,
        current_timestamp() AS rebuilt_at
    FROM bal b
    LEFT JOIN raw_mov r  USING (as_of, account_id)
    LEFT JOIN conf_mov c USING (as_of, account_id)"""
)

# COMMAND ----------

# MAGIC %md ## `dq_cash_continuity` — does each account's ledger carry over?
# MAGIC
# MAGIC A different question from `dq_cash_integrity`'s: that check asks
# MAGIC whether *one day's own arithmetic* adds up (opening + movements =
# MAGIC closing); this one asks whether *consecutive days agree* — does
# MAGIC today's opening equal yesterday's closing? D-040 gave the clean book
# MAGIC that invariant for the first time; this is the check that was
# MAGIC promised alongside it, now that a broken delivery (a dropped or
# MAGIC duplicated entry) actually has something to break. `continuous` is
# MAGIC NULL on each account's first date — there is no prior day to compare,
# MAGIC the same boundary rule the performance tables use (D-042).

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.dq_cash_continuity
    COMMENT 'Per account-day: does the opening balance equal the previous business day''s closing? continuous is NULL on an account''s first date (nothing to compare).'
    AS
    WITH bal AS (
        SELECT as_of, account_id,
               MAX(CASE WHEN balance_type = 'OPENING' THEN amount END) AS opening,
               MAX(CASE WHEN balance_type = 'CLOSING' THEN amount END) AS closing,
               MAX(currency) AS currency
        FROM {SCHEMA}.silver_cash_balances
        GROUP BY as_of, account_id
    ),
    chained AS (
        SELECT as_of, account_id, opening, closing, currency,
               LAG(closing) OVER (PARTITION BY account_id ORDER BY as_of) AS prev_closing
        FROM bal
    )
    SELECT
        as_of,
        account_id,
        opening,
        prev_closing,
        CAST(opening - prev_closing AS DECIMAL(24,2)) AS delta,
        CASE WHEN prev_closing IS NULL THEN NULL ELSE opening = prev_closing END AS continuous,
        currency,
        current_timestamp() AS rebuilt_at
    FROM chained"""
)

# COMMAND ----------

# MAGIC %md ## `governance_cde_registry` — the register, queryable
# MAGIC
# MAGIC The Critical Data Element register (D-067) lives in the repo as YAML,
# MAGIC because an ownership change should be a reviewable diff rather than an
# MAGIC `UPDATE` nobody sees. But a register nobody can query is a register
# MAGIC nobody consults, so a resolved snapshot lands in the volume alongside
# MAGIC the FX rates and the securities master — the same pull-not-push
# MAGIC contract every other reference feed uses (D-006) — and this cell turns
# MAGIC it into a table.
# MAGIC
# MAGIC One row per column the platform **publishes**, not per column the
# MAGIC register *claims*. That difference is what lets the coverage metric
# MAGIC below be computed from the rows rather than asserted: an unclassified
# MAGIC column would arrive here with a NULL tier and drag the rate down. The
# MAGIC CI gate is what keeps it at 100%; this measures it independently.
# MAGIC
# MAGIC It lives in the `governance_` layer rather than under `dq_` because it
# MAGIC is not a check — it is the statement of accountability the checks are
# MAGIC measured against. It is built here only because `dq_metrics`, two
# MAGIC cells down, is the natural consumer.

# COMMAND ----------

REGISTRY_PATH = "/Volumes/workspace/parvum/landing/reference/cde_registry.json"

# Explicit rather than inferred: the landed file is a contract, and a schema
# written down is a contract that fails loudly when the producer changes
# shape. Inference would also silently retype a column that happened to be
# all-NULL on one particular day.
REGISTRY_SCHEMA = StructType(
    [
        StructField("table_name", StringType(), nullable=False),
        StructField("column_name", StringType(), nullable=False),
        StructField("layer", StringType(), nullable=False),
        StructField("description", StringType(), nullable=False),
        StructField("tier", StringType(), nullable=True),
        StructField("owner", StringType(), nullable=True),
        StructField("definition", StringType(), nullable=True),
        StructField("quality_rules", StringType(), nullable=True),
        StructField("quality_rule_count", LongType(), nullable=False),
        StructField("control_gap", StringType(), nullable=True),
        StructField("slo", StringType(), nullable=True),
        StructField("slo_objective", StringType(), nullable=True),
        StructField("slo_measured_by", StringType(), nullable=True),
        StructField("slo_target", StringType(), nullable=True),
        # Double on the way IN because that is what a JSON number is on the
        # wire — but it is CAST to DECIMAL before it is published, and it has
        # to be. See the projection below.
        StructField("slo_attainment_objective", DoubleType(), nullable=True),
        StructField("slo_window_days", LongType(), nullable=True),
    ]
)

spark.read.schema(REGISTRY_SCHEMA).json(REGISTRY_PATH).createOrReplaceTempView(  # noqa: F821
    "cde_registry_landed"
)

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.governance_cde_registry
    COMMENT 'The Critical Data Element register, resolved: one row per column the platform publishes, with its tier, owner, business definition, service level, and either the quality rules that test it or a stated control gap. Source of truth is governance/cde_registry.yml in the repo; this is a landed snapshot of it.'
    AS
    SELECT
        table_name,
        column_name,
        layer,
        description,
        tier,
        owner,
        definition,
        quality_rules,
        quality_rule_count,
        control_gap,
        slo,
        slo_objective,
        slo_measured_by,
        slo_target,
        -- DECIMAL, not the DOUBLE it arrives as. Three reasons, and the first
        -- one bit: the exporter's wire-type converter map is deliberately
        -- closed, so an unknown type stops the export loudly rather than
        -- guessing (which is what it did -- "no converter for
        -- slo_attainment_objective: DOUBLE"). Second, the Postgres column
        -- this lands in is numeric(14,6) (V11), and the types should agree.
        -- Third, nothing else this platform publishes is a float: the estate
        -- is Decimal throughout, deliberately, and one DOUBLE would be the
        -- exception that teaches the wrong lesson. Do not "simplify" this
        -- cast away.
        CAST(slo_attainment_objective AS DECIMAL(14,6)) AS slo_attainment_objective,
        slo_window_days,
        current_timestamp() AS rebuilt_at
    FROM cde_registry_landed"""
)

print(
    "governance_cde_registry rows:",
    spark.table(f"{SCHEMA}.governance_cde_registry").count(),  # noqa: F821
)

# COMMAND ----------

# MAGIC %md ## `dq_metrics` — the whole quality layer, one declarative table
# MAGIC
# MAGIC Every check above lives in its own table, at its own grain, because
# MAGIC each one needs different detail to be useful for tracing a specific
# MAGIC break back to its cause. But a Data Operations KPI dashboard doesn't
# MAGIC want detail — it wants a trend: is the pipeline healthy today, was it
# MAGIC healthy last week, which dimension is driving the exception count.
# MAGIC `dq_metrics` is that rollup: one row per (date, dimension, metric),
# MAGIC declarative in the sense that adding a new check later means adding
# MAGIC one more `SELECT` to the `UNION ALL`, never a schema change.
# MAGIC
# MAGIC Five dimensions:
# MAGIC - **freshness** — one row per rebuild (not per historical date; staleness
# MAGIC   is inherently "how current is the pipeline right now", not a fact
# MAGIC   about a past day), dated at the rebuild's own run date. How many
# MAGIC   calendar days bronze's latest delivery lags behind today.
# MAGIC - **completeness** — per business day, the share of the day's 11
# MAGIC   expected files (5 accounts × 2 holdings formats + 1 consolidated
# MAGIC   cash file) that actually parsed.
# MAGIC - **accuracy** — per business day, three rates: cross-format holdings
# MAGIC   agreement, intra-day cash arithmetic, and the new day-over-day cash
# MAGIC   continuity. All three are legitimately below 100% most days — the
# MAGIC   defects are deliberately injected at a known rate, so a KPI
# MAGIC   dashboard showing "accuracy SLA attainment: ~40%" here is the
# MAGIC   correct, honest number for *this* fixture, not a bug.
# MAGIC - **exceptions** — per business day, the raw counts behind the three
# MAGIC   accuracy rates above, for trend and aging charts (a rate alone
# MAGIC   hides whether a bad day was one big break or many small ones).
# MAGIC - **governance** — one row per rebuild, like freshness, because the
# MAGIC   register describes the estate as it is now rather than as it was on
# MAGIC   some past business day. How much of what we publish is classified,
# MAGIC   and how much of what we call critical is actually tested.
# MAGIC
# MAGIC `passed` carries a threshold verdict only where one honestly applies
# MAGIC (a rate against a target); exception counts are trend data, not a
# MAGIC pass/fail, and stay NULL.

# COMMAND ----------

spark.sql(  # noqa: F821
    f"""CREATE OR REPLACE TABLE {SCHEMA}.dq_metrics
    COMMENT 'Declarative DQ rollup: one row per (date, dimension, metric). freshness/completeness/accuracy/exceptions/governance, aggregated from the detail tables above plus bronze_file_registry. passed is NULL where no fixed threshold applies (exception counts).'
    AS
    WITH days AS (
        SELECT DISTINCT statement_date AS as_of FROM {SCHEMA}.bronze_file_registry
    ),
    file_counts AS (
        SELECT statement_date AS as_of, SUM(CASE WHEN status = 'PARSED' THEN 1 ELSE 0 END) AS parsed
        FROM {SCHEMA}.bronze_file_registry
        GROUP BY statement_date
    ),
    position_counts AS (
        SELECT as_of, COUNT(*) AS n FROM {SCHEMA}.silver_positions GROUP BY as_of
    ),
    holdings_findings AS (
        SELECT as_of, COUNT(*) AS n FROM {SCHEMA}.dq_holdings_recon GROUP BY as_of
    ),
    cash_integrity_counts AS (
        SELECT as_of, COUNT(*) AS total,
               SUM(CASE WHEN conformed_consistent THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN NOT conformed_consistent THEN 1 ELSE 0 END) AS breaks
        FROM {SCHEMA}.dq_cash_integrity
        GROUP BY as_of
    ),
    cash_continuity_counts AS (
        -- Only rows where continuous IS NOT NULL: an account's first date has
        -- nothing to compare, and must not silently read as "0 breaks".
        SELECT as_of, COUNT(*) AS checked,
               SUM(CASE WHEN continuous THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN continuous = FALSE THEN 1 ELSE 0 END) AS breaks
        FROM {SCHEMA}.dq_cash_continuity
        WHERE continuous IS NOT NULL
        GROUP BY as_of
    ),
    completeness AS (
        SELECT d.as_of, 'completeness' AS dimension, 'files_landed_rate' AS metric,
               CAST(COALESCE(f.parsed, 0) / 11.0 AS DECIMAL(14,6)) AS value,
               COALESCE(f.parsed, 0) = 11 AS passed,
               CONCAT(CAST(COALESCE(f.parsed, 0) AS STRING), ' of 11 expected files parsed') AS detail
        FROM days d
        LEFT JOIN file_counts f USING (as_of)
    ),
    accuracy_holdings AS (
        SELECT d.as_of, 'accuracy' AS dimension, 'holdings_cross_format_match_rate' AS metric,
               CAST(1 - (COALESCE(h.n, 0) / NULLIF(p.n, 0)) AS DECIMAL(14,6)) AS value,
               COALESCE(h.n, 0) = 0 AS passed,
               CONCAT(CAST(COALESCE(h.n, 0) AS STRING), ' cross-format findings across ',
                      CAST(COALESCE(p.n, 0) AS STRING), ' positions') AS detail
        FROM days d
        LEFT JOIN holdings_findings h USING (as_of)
        LEFT JOIN position_counts p USING (as_of)
    ),
    accuracy_cash AS (
        SELECT d.as_of, 'accuracy' AS dimension, 'cash_conformed_consistency_rate' AS metric,
               CAST(COALESCE(c.ok, 0) / NULLIF(c.total, 0) AS DECIMAL(14,6)) AS value,
               COALESCE(c.breaks, 0) = 0 AS passed,
               CONCAT(CAST(COALESCE(c.ok, 0) AS STRING), ' of ', CAST(COALESCE(c.total, 0) AS STRING),
                      ' account-days consistent') AS detail
        FROM days d
        LEFT JOIN cash_integrity_counts c USING (as_of)
    ),
    accuracy_continuity AS (
        SELECT d.as_of, 'accuracy' AS dimension, 'cash_day_over_day_continuity_rate' AS metric,
               CAST(COALESCE(cc.ok, 0) / NULLIF(cc.checked, 0) AS DECIMAL(14,6)) AS value,
               COALESCE(cc.breaks, 0) = 0 AS passed,
               CONCAT(CAST(COALESCE(cc.ok, 0) AS STRING), ' of ', CAST(COALESCE(cc.checked, 0) AS STRING),
                      ' accounts continuous from the prior day') AS detail
        FROM days d
        LEFT JOIN cash_continuity_counts cc USING (as_of)
        WHERE cc.checked IS NOT NULL
    ),
    exceptions_holdings AS (
        SELECT d.as_of, 'exceptions' AS dimension, 'holdings_findings_count' AS metric,
               CAST(COALESCE(h.n, 0) AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(COALESCE(h.n, 0) AS STRING), ' cross-format findings') AS detail
        FROM days d
        LEFT JOIN holdings_findings h USING (as_of)
    ),
    exceptions_cash AS (
        SELECT d.as_of, 'exceptions' AS dimension, 'cash_integrity_breaks_count' AS metric,
               CAST(COALESCE(c.breaks, 0) AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(COALESCE(c.breaks, 0) AS STRING), ' account-days with a missing movement') AS detail
        FROM days d
        LEFT JOIN cash_integrity_counts c USING (as_of)
    ),
    exceptions_continuity AS (
        SELECT d.as_of, 'exceptions' AS dimension, 'cash_continuity_breaks_count' AS metric,
               CAST(COALESCE(cc.breaks, 0) AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(COALESCE(cc.breaks, 0) AS STRING), ' accounts broke day-over-day continuity') AS detail
        FROM days d
        LEFT JOIN cash_continuity_counts cc USING (as_of)
        WHERE cc.checked IS NOT NULL
    ),
    freshness AS (
        -- The one metric that is a fact about NOW, not about a historical
        -- as_of — dated at the rebuild's own run date on purpose.
        SELECT CURRENT_DATE() AS as_of, 'freshness' AS dimension, 'bronze_days_behind' AS metric,
               CAST(DATEDIFF(CURRENT_DATE(), MAX(statement_date)) AS DECIMAL(14,6)) AS value,
               DATEDIFF(CURRENT_DATE(), MAX(statement_date)) <= 3 AS passed,
               CONCAT('bronze last landed ', CAST(MAX(statement_date) AS STRING)) AS detail
        FROM {SCHEMA}.bronze_file_registry
    ),
    -- Governance: facts about the register, not about a business day, so
    -- dated at the rebuild's own run date exactly like freshness above.
    governance_counts AS (
        SELECT COUNT(*) AS published,
               SUM(CASE WHEN tier IS NOT NULL THEN 1 ELSE 0 END) AS classified,
               SUM(CASE WHEN tier = 'critical' THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN tier = 'critical' AND quality_rule_count > 0 THEN 1 ELSE 0 END) AS controlled,
               SUM(CASE WHEN tier = 'critical' AND quality_rule_count = 0
                             AND control_gap IS NOT NULL THEN 1 ELSE 0 END) AS gapped
        FROM {SCHEMA}.governance_cde_registry
    ),
    governance_classified AS (
        SELECT CURRENT_DATE() AS as_of, 'governance' AS dimension, 'columns_classified_rate' AS metric,
               CAST(classified / NULLIF(published, 0) AS DECIMAL(14,6)) AS value,
               classified = published AS passed,
               CONCAT(CAST(classified AS STRING), ' of ', CAST(published AS STRING),
                      ' published columns classified in the register') AS detail
        FROM governance_counts
    ),
    governance_control AS (
        -- 0.8 is a stated target, set when the estate delivered 0.357 and
        -- unmoved since; it was crossed at D-073. The point stands: a target
        -- quietly set to today's number is not a target, and an admitted
        -- control gap is manageable where a hidden one is not.
        SELECT CURRENT_DATE() AS as_of, 'governance' AS dimension, 'critical_control_coverage_rate' AS metric,
               CAST(controlled / NULLIF(critical, 0) AS DECIMAL(14,6)) AS value,
               controlled >= 0.8 * critical AS passed,
               CONCAT(CAST(controlled AS STRING), ' of ', CAST(critical AS STRING),
                      ' critical elements have a quality rule; target 80%') AS detail
        FROM governance_counts
    ),
    governance_critical AS (
        SELECT CURRENT_DATE() AS as_of, 'governance' AS dimension, 'critical_element_count' AS metric,
               CAST(critical AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(critical AS STRING), ' of ', CAST(published AS STRING),
                      ' published columns are classified critical') AS detail
        FROM governance_counts
    ),
    governance_gaps AS (
        SELECT CURRENT_DATE() AS as_of, 'governance' AS dimension, 'control_gap_count' AS metric,
               CAST(gapped AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(gapped AS STRING),
                      ' critical elements have a stated control gap and no automated rule') AS detail
        FROM governance_counts
    ),
    -- The alts chain has validated every document against the rest of its
    -- fund since D-050 -- commitment continuity, call sequencing, statement
    -- chaining -- and none of that reached the rollup, which is what the
    -- register's own control gap on those columns has said all along. Dated
    -- CURRENT_DATE() rather than a business day, like the governance rows
    -- above: the alts corpus is episodic, so this is a fact about the state
    -- of the document chain now, not about a feed day.
    alts_counts AS (
        SELECT COUNT(*) AS documents,
               SUM(CASE WHEN cross_document_valid THEN 1 ELSE 0 END) AS valid,
               SUM(CASE WHEN confirmed_fields_json IS NULL THEN 1 ELSE 0 END) AS unconfirmed
        FROM {SCHEMA}.silver_alts_documents
    ),
    accuracy_alts AS (
        SELECT CURRENT_DATE() AS as_of, 'accuracy' AS dimension,
               'alts_cross_document_valid_rate' AS metric,
               CAST(valid / NULLIF(documents, 0) AS DECIMAL(14,6)) AS value,
               valid = documents AS passed,
               CONCAT(CAST(valid AS STRING), ' of ', CAST(documents AS STRING),
                      ' private-fund documents reconcile against the rest of their fund') AS detail
        FROM alts_counts
    ),
    exceptions_alts AS (
        -- Not a failure: a document awaiting review is one gold is correctly
        -- declining to report (D-060). Counted so the queue's depth is
        -- visible rather than inferred from an empty tab.
        SELECT CURRENT_DATE() AS as_of, 'exceptions' AS dimension,
               'alts_documents_unconfirmed_count' AS metric,
               CAST(unconfirmed AS DECIMAL(14,6)) AS value, CAST(NULL AS BOOLEAN) AS passed,
               CONCAT(CAST(unconfirmed AS STRING),
                      ' private-fund documents have no confirmed values yet') AS detail
        FROM alts_counts
    )
    SELECT *, current_timestamp() AS rebuilt_at FROM completeness
    UNION ALL SELECT *, current_timestamp() FROM accuracy_holdings
    UNION ALL SELECT *, current_timestamp() FROM accuracy_cash
    UNION ALL SELECT *, current_timestamp() FROM accuracy_continuity
    UNION ALL SELECT *, current_timestamp() FROM exceptions_holdings
    UNION ALL SELECT *, current_timestamp() FROM exceptions_cash
    UNION ALL SELECT *, current_timestamp() FROM exceptions_continuity
    UNION ALL SELECT *, current_timestamp() FROM freshness
    UNION ALL SELECT *, current_timestamp() FROM governance_classified
    UNION ALL SELECT *, current_timestamp() FROM governance_control
    UNION ALL SELECT *, current_timestamp() FROM governance_critical
    UNION ALL SELECT *, current_timestamp() FROM governance_gaps
    UNION ALL SELECT *, current_timestamp() FROM accuracy_alts
    UNION ALL SELECT *, current_timestamp() FROM exceptions_alts"""
)

# COMMAND ----------

# MAGIC %md ## Column descriptions (Unity Catalog metadata)

# COMMAND ----------

COLUMN_COMMENTS = {
    "dq_holdings_recon": {
        "as_of": "Position date of the disagreeing copies",
        "account_id": "Custodial account the position sits in",
        "security_scheme": "Identifier scheme of security_id",
        "security_id": "Security identifier as it appears in the disagreeing copies",
        "finding": "MISSING_IN_SEMT002 | MISSING_IN_MT535 (position in one format only) | FIELD_MISMATCH (both present, a field differs)",
        "field": "Which field disagrees ('presence' for missing findings). cost_basis is never compared — structurally absent from semt.002",
        "semt002_value": "The semt.002 copy's value, as text (ABSENT for presence findings)",
        "mt535_value": "The MT535 copy's value, as text (ABSENT for presence findings)",
        "rebuilt_at": "When this reconciliation rebuild ran (UTC)",
    },
    "dq_cash_integrity": {
        "as_of": "Statement date being checked",
        "account_id": "Custodial account being checked",
        "opening": "Opening balance the file reported",
        "closing": "Closing balance the file reported",
        "movements_raw": "Type-signed sum of movements in raw bronze (feed duplicates included; BUY/FEE/TRANSFER_OUT negative)",
        "movements_conformed": "Type-signed sum of movements in conformed silver (duplicates collapsed)",
        "delta_raw": "opening + movements_raw − closing; 0 means the raw file is internally consistent",
        "delta_conformed": "opening + movements_conformed − closing; 0 means the conformed view is consistent",
        "raw_consistent": "TRUE when the custodian's file adds up as delivered",
        "conformed_consistent": "TRUE when the cleaned view adds up; FALSE here means a movement is genuinely missing (dropped by the feed)",
        "currency": "Native currency of the balances",
        "rebuilt_at": "When this reconciliation rebuild ran (UTC)",
    },
    "dq_cash_continuity": {
        "as_of": "Statement date being checked",
        "account_id": "Custodial account being checked",
        "opening": "Opening balance this statement reported",
        "prev_closing": "The previous business day's closing balance for this account; NULL on the account's first date",
        "delta": "opening − prev_closing; 0 means the ledger carried over cleanly",
        "continuous": "TRUE when opening = prev_closing; FALSE means a delivered file broke the chain; NULL on the first date (nothing to compare)",
        "currency": "Native currency of the balances",
        "rebuilt_at": "When this reconciliation rebuild ran (UTC)",
    },
    "governance_cde_registry": {
        "table_name": "The table this column belongs to. Grain: one row per (table, column) the platform publishes",
        "column_name": "The column being classified",
        "layer": "Medallion layer, derived from the table-name prefix (bronze/silver/dq/gold/governance)",
        "description": "The catalog description the publishing Spark job applies to this column",
        "tier": "critical (the business consumes it directly), supporting (feeds or qualifies a critical element), or operational (pipeline plumbing). NULL means published but unclassified — the CI gate blocks that, so it should never appear here",
        "owner": "The role accountable for this column's meaning and quality — a role, never a person, so ownership survives people changing jobs",
        "definition": "What this element means in business terms and why a wrong value matters. Required for critical, optional below it",
        "quality_rules": "Comma-separated dq_metrics metric names that test this element; empty when none does",
        "quality_rule_count": "How many quality rules cite this element — carried separately so counting needs no string parsing",
        "control_gap": "For a critical element with no quality rule: what is missing and what would close it. The register requires one or the other, never silence",
        "slo": "Name of the service level this element is held to (see slo_measured_by / slo_target)",
        "slo_objective": "What that service level promises, in one sentence — the thing the target is a threshold for",
        "slo_measured_by": "The dq_metrics metric that evidences that service level",
        "slo_target": "The service level's stated objective, as a sentence — what the estate is held to, not a claim about current attainment",
        "slo_attainment_objective": "The machine-readable half of that objective: the share of days in the window on which slo_measured_by must have passed. What dq_slo_attainment measures against",
        "slo_window_days": "How many trailing days the service level is judged over",
        "rebuilt_at": "When this gold rebuild ran (UTC)",
    },
    "dq_metrics": {
        "as_of": "The business day this metric covers; for dimension='freshness' this is instead the rebuild's own run date, since staleness is a fact about now",
        "dimension": "freshness | completeness | accuracy | exceptions",
        "metric": "The specific named check within the dimension (e.g. holdings_cross_format_match_rate)",
        "value": "The metric's value: a 0-1 rate for freshness/completeness/accuracy metrics, a raw count for exceptions metrics",
        "passed": "TRUE/FALSE against a fixed threshold where one honestly applies; NULL for exceptions metrics (trend data, not pass/fail)",
        "detail": "Human-readable context behind the number (e.g. '4 of 5 account-days consistent')",
        "rebuilt_at": "When this reconciliation rebuild ran (UTC)",
    },
}

for _table, _comments in COLUMN_COMMENTS.items():
    for _col, _comment in _comments.items():
        _escaped = _comment.replace("'", "''")
        spark.sql(  # noqa: F821
            f"ALTER TABLE {SCHEMA}.{_table} ALTER COLUMN {_col} COMMENT '{_escaped}'"
        )
print(f"column comments applied to {len(COLUMN_COMMENTS)} dq tables")

# COMMAND ----------

# MAGIC %md ## What this run found

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT finding, field, COUNT(*) AS findings
        FROM {SCHEMA}.dq_holdings_recon
        GROUP BY finding, field
        ORDER BY findings DESC"""
    )
)

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT
            COUNT(*)                                            AS account_days,
            SUM(CASE WHEN NOT raw_consistent THEN 1 ELSE 0 END) AS raw_breaks,
            SUM(CASE WHEN NOT conformed_consistent THEN 1 ELSE 0 END) AS conformed_breaks,
            SUM(CASE WHEN NOT raw_consistent AND conformed_consistent
                     THEN 1 ELSE 0 END)                         AS collapse_vindicated
        FROM {SCHEMA}.dq_cash_integrity"""
    )
)

# COMMAND ----------

# MAGIC %md ## The KPI scorecard, most recent day

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""SELECT dimension, metric, value, passed, detail
        FROM {SCHEMA}.dq_metrics
        WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.dq_metrics WHERE dimension != 'freshness')
           OR dimension = 'freshness'
        ORDER BY dimension, metric"""
    )
)
