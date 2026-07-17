# Parvum — a wealth-data platform reference build

A small, honest reference implementation of a wealth-management data platform,
built end-to-end from open and synthetic data: custodial feeds in **real wire
formats** → normalisation against a **securities master** → **reconciliation &
data-quality control** → a **total-portfolio view** served by Java web
services — plus a human-in-the-loop pipeline for alternatives documents, and an
infra/observability wrapper.

The interesting constraint: the feeds are synthetic but the *formats* are real
(ISO 20022, SWIFT MT), seeded with real reference data and real SEC 13F
holdings, with defects injected deliberately — because the defects are what
drive reconciliation and data-quality work in practice.

## Architecture (target)

```mermaid
flowchart LR
    subgraph GHA [GitHub Actions cron — the fetch half, open egress]
        FG[Feed generator<br/>5 accounts × semt.002 / MT535<br/>+ consolidated camt.053<br/>+ injected defects]
        EX[13F filings<br/>ETF proxies]
    end
    GHA -->|raw files via CLI/API| UC[Unity Catalog volume]
    UC -->|file-arrival trigger| B[Bronze<br/>raw as received]
    B --> S[Silver<br/>normalised, ID-mapped]
    S --> G[Gold<br/>portfolio views]
    subgraph DBX [Databricks Free Edition — Delta Lake, Workflows]
        B --> S --> G
    end
    G -->|load| PG[(Postgres<br/>local Docker → RDS)]
    PG --> API[Quarkus + jOOQ REST<br/>AWS App Runner]
    API --> FE[React/Svelte frontend<br/>Vercel]
    PDF[Synthetic alts PDFs<br/>capital calls etc.] --> HITL[Extraction + confidence<br/>+ human review queue] --> S
```

Key split: **Databricks Free Edition has no open internet access**, so all
external fetching runs in GitHub Actions and lands files for Databricks to
process. Serving infra is provisioned on **real AWS by Terraform** (decision
[D-005](docs/DECISIONS.md)).

## Phases

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundations — repo, local Postgres, docs | ✅ done |
| 1 | Custodial feed ingestion → Bronze (semt.002, MT535, camt.053) | ✅ done |
| 2 | Reference data & normalisation → Silver | 🔄 in progress |
| 3 | Reconciliation & data-quality control | ⬜ |
| 4 | Portfolio aggregation & ownership graph → Gold | ⬜ |
| 5 | Java serving layer (Quarkus + jOOQ) + live site | ⬜ |
| 6 | Alternatives HITL pipeline | ⬜ |
| 7 | Liquidity & scenario projection view | ⬜ |
| 8 | External analytics integration (mocked) | ⬜ |
| 9 | Terraform + Grafana/Prometheus + PagerDuty | ⬜ |

## Quickstart

Prereqs: Docker Desktop (Linux containers), GNU make, git, Python 3.

```sh
make up      # start local Postgres 16, wait until healthy
make psql    # open a SQL shell
make help    # list all targets
```

Optional: `cp .env.example .env` to override local DB credentials/port.

### The feed pipeline

```sh
make fetch-13f                     # sync the local 13F filing store from SEC EDGAR
make generate                      # ~90 business days of feeds into data/raw
make generate DAYS=1               # just today's delivery
make generate DAYS=1 END=2026-07-10  # replay one historical day, byte-identically
make land                          # upload data/raw to the Unity Catalog volume
```

`make land` needs `DATABRICKS_HOST` in `.env` plus a Databricks CLI login. The
same two commands run unattended on weekdays via
[`daily-feeds.yml`](.github/workflows/daily-feeds.yml) — CI has no code path of
its own, it just sets `DAYS=1`.

Landing a file is all it takes: a **file-arrival trigger** starts the bronze
job, so nothing downstream has to know when the feed runs.

```sh
make deploy-job   # apply databricks.yml (the job defined as code)
make run-job      # run bronze now, without waiting for a file
```

The full loop — generate → land → parse to bronze — runs with no human in it.

## Repo layout

| Dir | Contents | Phase |
|-----|----------|-------|
| `ingest/` | feed generator + format parsers (Python) | 1 |
| `spark/` | Databricks notebooks/jobs — bronze/silver/gold | 1–4 |
| `reference/` | securities master (OpenFIGI, SEC, GLEIF) | 2 |
| `serving/` | Quarkus + jOOQ REST API | 5 |
| `alts-hitl/` | PDF extraction + review queue | 6 |
| `infra/` | docker-compose now; Terraform later | 0, 9 |
| `docs/` | [ARCHITECTURE](docs/ARCHITECTURE.md) · [DECISIONS](docs/DECISIONS.md) · [GLOSSARY](docs/GLOSSARY.md) · [BUILD_LOG](docs/BUILD_LOG.md) | all |
