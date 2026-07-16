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

## Current state (Phase 0)

Local Postgres 16 via `infra/docker-compose.yml` (volume-backed, healthcheck,
`make up`). Everything else is planned, not built.
