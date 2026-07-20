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
| `bronze_alts_ingest.py` | bronze | Registers every landed private-fund PDF (`bronze_alts_documents`) and every landed LLM extraction result (`bronze_alts_extractions`, D-049) — registration only, no parser (there is no deterministic parser for a PDF, and an extraction's fields are already structured by the time they land). Separate job (`alts_bronze_ingest` in `databricks.yml`) and separate landing paths (`landing/alts/raw/`, `landing/alts/extracted/`) from the custodial feeds — see D-047. |
| `silver_alts_documents.py` | silver | Cross-document validation for alts extractions (D-050): commitment continuity, call/distribution sequencing, capital-account statement chaining — the checks a single document's self-consistency can't make. Orchestration only; the logic lives in `alts-hitl`'s `parvum_alts_hitl.validate` (pytest-tested). Writes `silver_alts_documents`: a routing decision (`auto_accept` / `needs_review`) per document, never a corrected value. |

## Tables (schema `workspace.parvum`)

`bronze_file_registry` is the inventory: "what raw data do we have?" is
`SELECT format, status, COUNT(*) …` — not a directory listing. All bronze
tables carry `file_path` lineage back to the exact source file in the
landing volume, which itself is never modified (raw-as-received).
`bronze_alts_documents` is the same idea for private-fund PDFs.
