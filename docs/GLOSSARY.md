# Glossary

Domain terms and tools used in this project, one line each. House rule: no
magic — every term gets defined here on first use.

## Financial formats & data

- **ISO 20022** — the modern XML-based standard for financial messaging; messages are named `area.number` (e.g. `semt.002`).
- **semt.002** — ISO 20022 "Securities Statement of Holdings": a custodian's periodic statement of what an account holds.
- **camt.053** — ISO 20022 "Bank-to-Customer Statement": end-of-day cash account statement (balances + entries).
- **SWIFT MT** — the older fixed-tag text message standard (`:35B:`-style tags) still dominant in custody messaging.
- **MT535** — SWIFT MT statement of holdings (the MT counterpart of semt.002).
- **MT536** — SWIFT MT statement of transactions.
- **MT940 / MT942** — SWIFT MT end-of-day / intraday cash statements.
- **BAI2** — a positional text format for bank balance/cash reporting, common in treasury.
- **OFX** — Open Financial Exchange; retail-flavoured XML format used by consumer bank feeds.
- **Custodial feed** — the periodic file a custodian (the institution holding assets) sends describing positions, transactions and cash.
- **Cost basis** — what was originally paid for a position; needed for gains; frequently missing in feeds (a classic data-quality defect).
- **13F / 13F-HR** — quarterly SEC filing where large US institutional managers disclose their equity holdings; public domain.
- **EDGAR** — the SEC's public filing system (source of 13F data).
- **CIK** — SEC's Central Index Key, its identifier for a filing entity.
- **FIGI / OpenFIGI** — Financial Instrument Global Identifier; free, open instrument identifier with a free mapping API (Bloomberg-operated).
- **LEI / GLEIF** — Legal Entity Identifier; open global register of legal entities, published by GLEIF.
- **ISIN / CUSIP / SEDOL** — proprietary-ish security identifiers custodians actually put in feeds; mapping them to FIGI is the securities-master job.
- **Securities master** — the reference table of instruments (identifiers, names, types) everything else normalises against.
- **Reconciliation break** — a mismatch between two views that should agree (e.g. positions vs. accumulated transactions); the unit of data-quality work.
- **Benchmark proxy** — a free ETF price series standing in for a licensed index (e.g. an S&P 500 ETF for the S&P 500 itself).
- **ILPA** — Institutional Limited Partners Association; publishes *standardised templates* for capital-call and distribution notices — the closest thing to a public spec for alternatives documents.
- **Form ADV / Form D** — public SEC filings by investment advisers / for exempt private offerings; useful colour on private funds, but they never contain the GP↔LP documents themselves.
- **GP / LP** — General Partner (runs a private fund) / Limited Partner (invests in it); capital-call and distribution notices flow between them privately.
- **Capital call** — the GP's notice to LPs to pay in part of their committed capital to fund an investment; a core alternatives document.
- **Distribution (private funds)** — the GP returning cash or securities to LPs after an exit; announced by a distribution notice.

## Platform & tools

- **Medallion architecture** — bronze (raw as received) → silver (clean, conformed) → gold (aggregated, serving-ready) layering of a lakehouse.
- **Delta Lake** — Databricks' open table format: Parquet files + a transaction log giving ACID tables on object storage.
- **Unity Catalog** — Databricks' governance layer: catalogs/schemas/tables/volumes with permissions.
- **Unity Catalog volume** — file storage governed by Unity Catalog; our GitHub Actions push raw files here (Free Edition has no external bucket access).
- **Databricks Workflows** — Databricks' built-in job scheduler/orchestrator.
- **HITL** — human-in-the-loop: pipeline steps where low-confidence machine output is routed to a person for review.
- **Quarkus** — a Java framework optimised for fast startup and low memory (container-friendly), with optional native-image compilation.
- **jOOQ** — a Java library that generates typesafe code from your schema so you write explicit SQL, not ORM abstractions.
- **RDS / db.t4g.micro** — AWS managed Postgres; t4g.micro is the smallest ARM instance class (~£10/mo).
- **AWS App Runner** — AWS's closest thing to a PaaS: point it at a container image, get a scaled, TLS-terminated public HTTPS service.
- **ECR** — AWS's container image registry (where CI pushes the Quarkus image).
- **NAT gateway / ALB** — AWS networking components with meaningful fixed monthly cost (~£26 / ~£13); deliberately avoided here.
- **Terraform** — declarative infrastructure-as-code: `.tf` files describe cloud resources; `plan` previews, `apply` creates.
- **GitHub-hosted runner** — a fresh, ephemeral VM github.com provides to execute each GitHub Actions job (free for public repos); destroyed when the job ends.
- **Docker image / container / volume** — image = frozen template of a program + its dependencies; container = a running (disposable) instance of an image; named volume = Docker-managed storage that outlives containers — our local Postgres data lives in one.
- **uv** — fast Python package & environment manager: reads `pyproject.toml`, creates the virtualenv, writes `uv.lock`.
- **pyproject.toml / uv.lock** — the project's *declared* dependencies vs. the *exact pinned* resolution; committing the lockfile means CI and every machine install identical versions.
- **ruff** — Python linter *and* formatter in one fast tool (replaces flake8 + isort + black).
- **pytest** — the standard Python test framework; our tests double as documentation of model guarantees.
- **Pydantic** — Python library for data models that validate on construction; wrong shapes fail loudly at the boundary.
- **Canonical model** — the single internal representation all feed formats map to and from (hub-and-spoke: N formats = N parsers, not N×N conversions).
- **CI (continuous integration)** — automated checks (format, lint, tests) that run on every pull request and must pass before merge.
- **Luhn algorithm** — the mod-10 checksum used by ISINs (and card numbers); catches most single-character typos in an identifier.
- **Mermaid** — text-based diagram language rendered natively by GitHub in markdown; diagrams live in git and are reviewed like code.
- **JSON Schema** — a machine-readable description of a data structure; Pydantic emits one per model (`model_json_schema()`) — the formal contract you'd hand to another team.
- **ERD (entity-relationship diagram)** — a diagram of entities and how they relate; tools like erdantic generate them from Pydantic models, DBeaver/dbdiagram.io from live database schemas.
- **XML namespace** — the `xmlns="urn:..."` declaration that scopes an XML vocabulary; ISO 20022 messages carry their exact message version in it.
- **XSD** — XML Schema Definition: the machine-readable grammar for an XML format; validating a document against the official XSD proves spec fidelity (deferred here, D-010).
- **Round-trip test** — assert `parse(render(x)) == x`: proves renderer and parser agree, and documents exactly which fields a format cannot carry.
- **ISO 15022** — the standard behind SWIFT MT5xx securities messages: `:TAG::QUALIFIER//value` fields inside `:16R:`/`:16S:` blocks; the predecessor vocabulary ISO 20022 XML-ified.
- **Decimal comma (SWIFT)** — MT numbers use a comma as the decimal mark and always include it (`220,` = 220); a classic feed-parser trap.
- **Narrative field** — a free-text field (e.g. MT535's `:70E:`) that real feeds routinely use to smuggle structured data the format has no proper slot for; parsing conventions out of narrative is authentic feed work.
- **OPBD / CLBD** — ISO balance codes in camt.053: opening booked / closing booked balance.
- **Booking date vs value date** — when a bank *recorded* an entry vs when the money *takes effect*; camt.053 carries both (`BookgDt`/`ValDt`), mapped to our trade/settlement dates.
- **CdtDbtInd** — camt.053's credit/debit indicator (CRDT = money in, DBIT = money out); we derive it from the transaction type and deliberately don't cross-check on parse (an inconsistent pair is a data-quality catch, not a parse failure).
- **Proprietary code (BkTxCd/Prtry)** — camt.053's slot for a bank's own transaction vocabulary; mapping proprietary codes to a canonical taxonomy is a core feed-onboarding task.
- **Defect injection** — deliberately corrupting generated feeds (from a random seed, so exactly reproducible) to give reconciliation and data-quality controls something real to catch.
- **Injection manifest** — the record of every seeded defect (what, where, before→after); the ground truth that detection is later measured against.
- **Semantic vs syntactic defect** — a file that parses but lies (caught by data-quality rules downstream) vs a file that cannot be read at all (caught at the parser).
- **cron** — the standard time-based schedule syntax (`0 6 * * *` = daily at 06:00 UTC); used by GitHub Actions `schedule:` triggers.
- **EventBridge Scheduler / Lambda** — AWS's native cron + serverless functions; the in-cloud alternative to Actions cron (considered in D-006).
- **Idempotent** — safe to run twice: rerunning produces the same end state, no duplicates. A required property of every load/fetch job here.
- **Upsert / MERGE** — insert-or-update in one statement; how daily loads apply new data on top of existing rows without duplication.
- **System of record** — the authoritative copy of the data (here: the Delta lakehouse); every other store is a rebuildable projection of it.
- **Medallion architecture** — see above; note it's a *pattern name* (popularised by Databricks), not a technology — bronze/silver/gold is just disciplined layered ETL.
