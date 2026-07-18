# Architecture

Living doc — updated as each phase lands. The README holds the one-glance
diagram; this file holds the reasoning.

## The shape

Five layers, mirroring a real wealth-data platform:

1. **Acquisition** — synthetic custodial feeds generated in real wire formats
   (semt.002, MT535, camt.053) with deliberately injected defects, plus real
   external pulls (SEC 13F, ETF benchmark proxies) fetched by GitHub Actions.
2. **Processing** — Databricks Free Edition: Delta Lake tables in a medallion
   layout (bronze = raw as received, silver = normalised & identifier-mapped,
   gold = serving-ready portfolio views), orchestrated by Databricks Workflows.
3. **Reference data** — a small real securities master (~50–100 instruments)
   built from OpenFIGI + SEC ticker/CIK + a few GLEIF LEIs.
4. **Serving** — gold tables loaded to Postgres; Quarkus + jOOQ REST API;
   small React/Svelte frontend. Local dev on Docker; production on AWS
   (RDS + App Runner) provisioned by Terraform.
5. **Control & ops** — reconciliation + data-quality framework (Phase 3),
   the alts HITL review queue (Phase 6), Grafana/Prometheus + PagerDuty (Phase 9).

## Load-bearing constraints (why it's shaped this way)

- **Databricks Free Edition cannot reach the open internet.** All external
  fetching therefore runs in GitHub Actions, which pushes raw files into a
  Unity Catalog volume via the Databricks CLI/REST API. Fetch and process are
  separate services by design — the fetch log (what ran, what changed, what
  failed) is a first-class artefact.
- **AWS account is on the Free plan** ($200 credits, 6-month window, hard
  spend cap — cannot be charged). Some services may be restricted; verify App
  Runner availability before writing Terraform, fall back to ECS Fargate.
- **Databricks Free Edition is serverless-only, Python/SQL-only**, with daily
  compute quotas. Jobs must be small and idempotent.
- **Budget guardrails:** no NAT gateway (~£26/mo), no ALB (~£13/mo), no
  always-on Aurora Serverless. AWS budget alert before any resource exists.

## Scheduling — why two schedulers

The platform deliberately uses two schedulers (D-006):

- **GitHub Actions cron** (hosted runners on github.com) for anything that
  needs the open internet: fetching 13F filings from EDGAR, benchmark ETF
  prices. Databricks Free Edition compute cannot reach arbitrary external
  hosts, so fetch jobs run where egress is unrestricted and *land* files.
- **Databricks Workflows** for everything inside the lakehouse: the scheduled
  bronze→silver→gold processing runs. Databricks absolutely has a scheduler —
  it just can't do the fetching.

The split is also good design independent of the constraint: acquisition
(flaky networks, retries, rate limits) is isolated from processing
(deterministic, replayable), with the landed file as the clean contract
between them.

## Environments

Three layers, no standing staging environment (D-007):

1. **Local dev** — Docker Compose; Postgres pinned to the same major version
   as the RDS target, so SQL behaves identically.
2. **CI** — every pull request runs lint + tests on GitHub Actions before it
   can merge.
3. **Live** — the single AWS environment, provisioned by Terraform.

Parity comes from pinned versions and shared Terraform modules, not from a
duplicate staging stack; an ephemeral staging environment via Terraform
workspaces is the documented scale-up path if ever needed.

## Serving store lifecycle

Postgres is a **durable, continuously updated projection of the gold layer**
— not transient, and not the system of record:

- Each export run **truncates and reloads** the projection tables (D-029) —
  gold itself is a full rebuild carrying complete history, so the projection
  mirrors it exactly rather than accumulating alongside it; an upsert that
  never deletes would silently keep rows a gold restatement removed.
- The **Delta lakehouse is the system of record**: it keeps raw-as-received
  bronze forever and can rebuild every downstream table.
- The gold→Postgres load is therefore trivially **idempotent** — Postgres can
  be dropped and rebuilt from gold at any time. Operationally: valuable, but
  disposable.
- **Schema-per-tenant** (D-028): every tenant (advisory firm) has its own
  Postgres schema with identical layout, migrated by Flyway at startup;
  isolation is structural, not a WHERE clause.

## Current state (end of Phase 4)

The lakehouse side is complete and unattended: a daily GitHub Action fetches
13F filings and ECB FX rates, generates and lands the day's feed files, and a
file-arrival trigger runs the five-task Databricks job — bronze (parse,
restatement-aware) → silver positions ∥ silver cash (conformed,
owner-attributed) → reconciliation (cross-format findings + cash integrity,
graded against the generator's defect manifests) → gold (client wealth,
allocation, income, top holdings; USD headlines at each day's ECB rate).
Failure email and a freshness gate watch the chain.

The serving layer (Phase 5) is under construction: the Quarkus application
in `serving/` starts, migrates every tenant schema (Flyway, schema-per-tenant
per D-028), and reports healthy against the local Postgres 16 from
`infra/docker-compose.yml`; its tests run the same way against a throwaway
container in CI. The gold→Postgres exporter, the jOOQ query layer and
endpoints, and the AWS deployment are next. Alts-HITL and
Terraform/observability remain planned, not built.
