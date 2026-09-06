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
| `bronze_ingest.py` | bronze | Registers every landed file in `bronze.file_registry` (path, format, date, checksum, status) and parses semt.002 / MT535 / camt.053 into `bronze.holdings`, `bronze.cash_entries`, `bronze.cash_balances`. Failures land in the registry as `FAILED` rows — recorded, not fatal. |
| `bronze_alts_ingest.py` | bronze | Registers every landed private-fund PDF (`bronze.alts_documents`) and every landed LLM extraction result (`bronze.alts_extractions`, D-049) — registration only, no parser (there is no deterministic parser for a PDF, and an extraction's fields are already structured by the time they land). Separate job (`alts_bronze_ingest` in `databricks.yml`) and separate landing paths (`landing/alts/raw/`, `landing/alts/extracted/`) from the custodial feeds — see D-047. |
| `silver_alts_documents.py` | silver | Cross-document validation for alts extractions (D-050): commitment continuity, call/distribution sequencing, capital-account statement chaining — the checks a single document's self-consistency can't make. Orchestration only; the logic lives in `alts-hitl`'s `parvum_alts_hitl.validate` (pytest-tested). Writes `silver.alts_documents`: a routing decision (`auto_accept` / `needs_review`) per document, never a corrected value. |

## Catalog layout

Tables live in a dedicated `parvum` Unity Catalog catalog with **one schema
per medallion layer** — `parvum.bronze`, `parvum.silver`, `parvum.gold`,
plus `parvum.dq` for the data-quality control tables and `parvum.governance`
for the CDE register snapshot. The layer is the schema, so table names drop
the redundant prefix: `parvum.gold.client_wealth`, not
`workspace.parvum.gold_client_wealth`. Access policy attaches to a schema, so
"analysts read `gold`, only the pipeline writes `silver`/`bronze`" is a
single grant.

The raw landing zone stays at `workspace.parvum.landing` (the volume under
`/Volumes/workspace/parvum/landing/`). It holds files, not medallion tables,
and the file-arrival trigger and daily feed Action are wired to that path.

`bronze.file_registry` is the inventory: "what raw data do we have?" is
`SELECT format, status, COUNT(*) …` — not a directory listing. All bronze
tables carry `file_path` lineage back to the exact source file in the
landing volume, which itself is never modified (raw-as-received).
`bronze.alts_documents` is the same idea for private-fund PDFs.
