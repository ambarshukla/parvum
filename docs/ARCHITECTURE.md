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
   Each layer is its own Unity Catalog schema in a `parvum` catalog —
   `parvum.bronze`, `parvum.silver`, `parvum.gold`, plus `parvum.dq` (control
   tables) and `parvum.governance` (the CDE register snapshot) — so access
   policy and discovery attach to the layer. The raw landing volume stays in
   `workspace.parvum.landing`; it holds files, not tables.
3. **Reference data** — a small real securities master (~50–100 instruments)
   built from OpenFIGI + SEC ticker/CIK + a few GLEIF LEIs.
4. **Serving** — gold tables loaded to Postgres; Quarkus + jOOQ REST API;
   small React/Svelte frontend. Local dev on Docker; production on a single
   host under Docker Compose behind Caddy (D-092). It ran on AWS (RDS + ECS
   Express Mode, provisioned by Terraform) until the free credits ran down;
   `infra/terraform/` is retained as the record of that.
5. **Control & ops** — reconciliation + data-quality framework (Phase 3),
   the alts HITL review queue (Phase 6), Grafana/Prometheus + PagerDuty (Phase 8).
   Unlike the client dashboard, this layer needs a real access-control
   boundary (write actions + an audit trail), so it lives in its own
   authenticated app, `internal/` (D-046) — a separate Vercel deployment
   calling the same serving API under `/internal/**`, gated by a session
   cookie. The Ops scorecard already lives here; the alts review queue
   (Phase 6) is next.

## Load-bearing constraints (why it's shaped this way)

- **Databricks Free Edition cannot reach the open internet.** All external
  fetching therefore runs in GitHub Actions, which pushes raw files into a
  Unity Catalog volume via the Databricks CLI/REST API. Fetch and process are
  separate services by design — the fetch log (what ran, what changed, what
  failed) is a first-class artefact.
- **Hosting is one small VM (~€4/mo), paid for and not time-limited.** The
  earlier AWS deployment ran on a $200 credit grant that was always finite;
  it exhausted at a measured $2.56/day, half of which was a managed load
  balancer fronting a single container (D-092). A free grant is a deadline
  wearing a discount's clothing — worth knowing before building on one.
- **Verify a managed service still accepts new customers before writing
  Terraform for it** — App Runner closed to new signups on 2026-04-30 and
  this was discovered at first `apply` (D-035).
- **Databricks Free Edition is serverless-only, Python/SQL-only**, with daily
  compute quotas. Jobs must be small and idempotent.
- **Budget guardrails:** the surviving lesson is that the guardrail must
  measure the right number. The AWS budget alert never fired — it was
  declared in Terraform but never present in the account, and the default one
  sat at 336% unread (D-092). Cost now has no variable component to guard.

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
   as production, so SQL behaves identically. Production runs the same
   Compose shape, which is what makes that parity cheap.
2. **CI** — every pull request runs lint + tests on GitHub Actions before it
   can merge.
3. **Live** — one host, `infra/hetzner/docker-compose.yml`, deployed by CI
   over an SSH key restricted to a forced command (D-092).

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
- **One exception to "disposable projection": the alts review queue**
  (D-051). It lives in a separate, non-tenant `internal` schema (its own
  Flyway migration location, `InternalSchema`) because it isn't client
  data at all — and unlike every tenant table, it takes real write
  traffic (a human's approve/correct decisions), so it can't simply be
  truncated and reloaded from gold. Corrections flow back to the
  lakehouse via a land-file reverse-sync (mirroring the existing fetch/
  land contract, reversed), not a direct write from the live service —
  Delta stays the system of record even for this one write-bearing table.

## Governance — a control beside the pipeline, not inside it

`governance/` holds the Critical Data Element register and the gate that
enforces it (D-067). It sits deliberately outside the dependency graph the
pipeline packages form: nothing in the workspace imports it, and it imports
nothing from the workspace. It *reads* `spark/*.py` and judges what it finds
there, which is the only relationship that lets a control stay independent of
the thing it controls.

The register covers every column the platform publishes — a tier and an owner
for each, and for the `critical` minority a business definition, a named SLO
and either the quality rules that test it or an explicitly stated gap. Its
authority comes from where it runs: `parvum-check-governance` is a CI status
check on every pull request, so a new column that nobody has classified stops
the merge, and an entry describing a column that no longer exists stops it
too. The register cannot drift from the schema because the build will not let
it.

A resolved snapshot of the register also lands in the volume beside the FX
rates and the securities master, where `spark/dq_recon.py` reads it into
`governance.cde_registry` and rolls coverage into `dq.metrics` under a
`governance` dimension (D-068). The YAML stays the source of truth — the
lakehouse holds a copy, not the original — so an ownership change is still a
reviewable diff rather than an `UPDATE` nobody sees. The snapshot carries
every column the platform publishes, including any that are unclassified, so
the coverage metric is computed from rows rather than asserted by the
producer.

The inventory it checks against is read out of the jobs, not out of Unity
Catalog. The jobs' `COLUMN_COMMENTS` dicts are what *sets* the catalog
comments, so they are the upstream truth, and they are readable in a pull
request before anything is deployed — which is the only point at which a gate
can still prevent something.

## Current state (end of Phase 4)

The lakehouse side is complete and unattended: a daily GitHub Action fetches
13F filings and ECB FX rates, generates and lands the day's feed files, and a
file-arrival trigger runs the five-task Databricks job — bronze (parse,
restatement-aware) → silver positions ∥ silver cash (conformed,
owner-attributed) → reconciliation (cross-format findings + cash integrity,
graded against the generator's defect manifests) → gold (client wealth,
allocation, income, top holdings, ownership graph; USD headlines at each
day's ECB rate). Failure email and a freshness gate watch the chain.

The serving layer (Phase 5) is live. The Quarkus application in `serving/`
migrates every tenant schema on boot (Flyway, schema-per-tenant per D-028).
The exporter (`export/`, D-029) pulls the gold tables over the SQL Statements
API and truncate-reloads each tenant schema — every gold row landing exactly
once, split per tenant. Read-only endpoints (`/tenants/{id}/…`) serve those
projections through jOOQ (D-030), routing each request to its tenant's schema
with a per-request `search_path`.

It runs on one host under Docker Compose behind Caddy, which terminates TLS
and reverse-proxies to a container that publishes no port of its own.
**Postgres is not reachable from the internet at all** — it binds to
loopback, and the two scheduled jobs that load it reach it through an SSH
tunnel whose key is pinned to a forced command and a single permitted
forward. That closed D-036's publicly-accessible database, which had existed
only because a hosted CI runner could not otherwise reach a private AWS
subnet (D-092).
