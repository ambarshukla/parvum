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
