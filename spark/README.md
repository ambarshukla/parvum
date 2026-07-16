# spark/

Databricks notebooks (committed as notebook-source `.py` files) for the
bronze → silver → gold pipeline on Delta Lake. Nothing here runs locally —
Databricks Free Edition (serverless) is the execution environment.

## Running in Databricks

The repo syncs into the workspace as a **Git folder**, so notebooks import
the `parvum_ingest` package straight from `../ingest/src` — the same code
that generates the feeds also parses them in the pipeline.

1. Workspace → Repos (or "Git folders") → Add → `https://github.com/ambarshukla/parvum`.
2. Open `spark/bronze_ingest.py`, attach serverless compute, **Run all**.
3. Re-runs are idempotent: files already in the registry are skipped.

## Notebooks

| Notebook | Layer | What it does |
|----------|-------|--------------|
| `bronze_ingest.py` | bronze | Registers every landed file in `bronze_file_registry` (path, format, date, checksum, status) and parses semt.002 / MT535 / camt.053 into `bronze_holdings`, `bronze_cash_entries`, `bronze_cash_balances`. Failures land in the registry as `FAILED` rows — recorded, not fatal. |

## Tables (schema `workspace.parvum`)

`bronze_file_registry` is the inventory: "what raw data do we have?" is
`SELECT format, status, COUNT(*) …` — not a directory listing. All bronze
tables carry `file_path` lineage back to the exact source file in the
landing volume, which itself is never modified (raw-as-received).
