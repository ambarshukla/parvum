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
| `bronze_alts_ingest.py` | bronze | Registers every landed private-fund PDF (capital call, distribution, capital account statement) in `bronze_alts_documents` — registration only, no parser (there is no deterministic parser for a PDF; extraction is a later, separate LLM step outside Databricks). Separate job (`alts_bronze_ingest` in `databricks.yml`) and separate landing path (`landing/alts/raw/`) from the custodial feeds — see D-047. |

## Tables (schema `workspace.parvum`)

`bronze_file_registry` is the inventory: "what raw data do we have?" is
`SELECT format, status, COUNT(*) …` — not a directory listing. All bronze
tables carry `file_path` lineage back to the exact source file in the
landing volume, which itself is never modified (raw-as-received).
`bronze_alts_documents` is the same idea for private-fund PDFs.
