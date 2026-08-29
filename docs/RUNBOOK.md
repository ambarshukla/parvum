# Runbook — operating the pipeline

The handoff standard. If an alert fires and you did not build this, everything
you need to act is here: what the alert means, the first three checks, what to
do, and when to escalate.

The rule this document is written to: **an alert nobody can action is noise,
and noise is worse than silence** — it teaches people to ignore the channel
that will one day carry something real. Every alert below therefore names an
owner and a decision, not just a symptom.

Related: [PERSONAS.md](PERSONAS.md) (who this is for), [ROADMAP.md](ROADMAP.md),
[ARCHITECTURE.md](ARCHITECTURE.md), and the service levels themselves in
[`governance/cde_registry.yml`](../governance/cde_registry.yml).

## Ownership boundary

| Layer | Owned by | Can change it? |
|---|---|---|
| The daily feed Action, the landing volume, the Databricks job | **Operator** | Re-run, re-land, pause. Not the code. |
| Spark jobs, the register, quality rules, SLO objectives | **Producer** | Via a pull request. The gate enforces the obligations. |
| The serving API, Postgres projection, both front ends | **Producer** | Via a pull request; deploys are automatic on merge. |
| Whether a breach is acceptable this week | **Operator**, escalating to the producer if it recurs | — |

An operator can always **re-run**; an operator never **edits gold**. If the
fix requires changing a number rather than re-producing it, that is a producer
change and goes through review — which is the entire point of the pipeline
being reproducible.

## Service levels, and what a breach means

Attainment is on the internal app's Ops page under **Service levels**, and in
the lakehouse as `workspace.parvum.dq_slo_attainment`. Objectives live in the
register; nothing here restates them, because two copies of a target drift.

**Reading the page:** the tiles at the top say what is true *now* — how stale
the feed is, whether today's files all landed, and any quality metric no
service level covers. The Service levels table says whether the estate is
meeting what it promised, over each SLO's own window. A metric the table
reports on has no tile, deliberately: it would state the same thing over a
different window and the two numbers would disagree (D-083).

Three states, and they are not two:

| Status | Meaning | Action |
|---|---|---|
| **Met** | Attainment is at or above the objective across the window. | None. |
| **Breached** | Below the objective. The error budget is spent. | Follow the entry below for the metric. |
| **Not enough history** | Fewer than 7 days in the window carry a verdict. | Not a pass. Check *why* the series is short before trusting anything else on the page. |

### ⚠️ Two SLOs are breached by design — do not "fix" them

`holdings_agreement` and `cash_ledger_integrity` ship breached and are
**expected to stay breached**. The feed generator injects defects at a rate no
real custodian would (D-011), so cross-format disagreements and cash-integrity
breaks are manufactured on purpose to give the reconciliation layer something
to find. The objective is what a real deployment would hold the feed to; the
breach is a property of the test corpus.

**What would actually be wrong:** those two reading *green*. That would mean
the defect injector had stopped, and the DQ layer was proving nothing.

They are left visibly red rather than exempted because an exemption list is
where uncomfortable numbers go to be forgotten.

## Alerts

### 1 · Databricks job failure email — `parvum-ingest` failed

**Means:** a task in the five-task chain raised. Nothing downstream ran, so
gold, the projection and both front ends still hold yesterday's figures. No
wrong data is being served — it is stale, and staleness is visible.

**First three checks:**
1. Which task? `bronze` implies a malformed or unexpected landed file; `silver`/`gold` implies a code or reference-data problem.
2. Open the run in Databricks → the failing task's output. The parsers record failures as `FAILED` rows in `bronze_file_registry` rather than raising, so a *raise* is unusual and specific.
3. `SELECT * FROM workspace.parvum.bronze_file_registry WHERE status <> 'PARSED' ORDER BY statement_date DESC LIMIT 20`.

**Do:** re-run the job (`make run-job`). It is idempotent end to end — bronze
skips files already registered by digest, and silver/gold/dq are full rebuilds.
A re-run is always safe and is the correct first move.

**Escalate to the producer if:** the same task fails twice on the same input.
That is a code problem, not a transient one.

### 2 · Long-run warning — the job exceeded 20 minutes

**Means:** a normal run is 9–12 minutes. Twenty means something is wedged or
the serverless quota is being consumed.

**First three checks:** is a previous run still active (`max_concurrent_runs`
is 1, so a hung run blocks the next)? Did the landed volume get an unusually
large drop? Is the warehouse cold?

**Do:** let it finish once. Cancel and re-run if it passes 30 minutes.

**Note:** `make run-job` itself now exceeds the CLI's ten-minute wait, and the
CLI being killed **does not stop the job**. Read the run state from
`/api/2.1/jobs/runs/get?run_id=…`, and parse the *run-level* `state` object —
grepping for `TERMINATED` matches the first task that finished and reports
success several minutes early.

### 3 · Freshness gate failed — bronze has stopped updating

**Means:** the thing job-failure email cannot catch. A job that never *starts*
sends nothing, and the file-arrival trigger does not fire on overwritten paths
(D-018). This gate is the dead-man's switch for that blind spot.

**First three checks:**
1. Did the daily GitHub Action run and land files? (Actions tab, `daily-feeds`.)
2. Did new `date=` directories appear in `/Volumes/workspace/parvum/landing/raw/`?
3. Did the trigger fire? Job page → Runs.

**Do:** if files landed but no run fired, `make run-job` by hand — this is the
D-018 case exactly. If nothing landed, the problem is upstream in the Action.

**Escalate if:** the Action succeeded and files are present and a manual run
also produces nothing new.

### 4 · A service level is newly breached

**Means:** something crossed from met to breached. Check it is not one of the
two that are breached by design above.

**First three checks:**
1. `SELECT * FROM workspace.parvum.dq_slo_attainment WHERE slo = '…'` — how many days, how much budget spent?
2. The underlying series: `SELECT as_of, value, passed, detail FROM workspace.parvum.dq_metrics WHERE metric = '<measured_by>' ORDER BY as_of DESC LIMIT 30`. One bad day or a trend?
3. The detail table behind that metric (`dq_cash_integrity`, `dq_holdings_recon`, `dq_cross_field_invariants`, `dq_return_plausibility`) for the failing dates.

**Do:** one bad day inside budget is an observation, not an incident. A trend,
or a budget going negative, is a producer conversation.

**`cross_field_consistency` or `return_plausibility` breaching is different.**
Those objectives are 1.0 with no error budget, because they are correctness
invariants: a break means two published figures disagree, or a client-visible
return moved in a way the market did not produce. **Escalate immediately** —
both are the shapes of defect that reached a live dashboard before (D-070,
D-072), and both are wrong numbers rather than bad days.

### 5 · The Ops page shows "Not enough history"

**Means:** fewer than 7 days in the window carry a verdict for that metric.

**Known and expected for `gold_freshness`:** `bronze_days_behind` is published
as a single as-of-now row rather than a daily series, so it can only ever have
one day of history. This is a real limitation of that metric's shape, recorded
here rather than smoothed over; closing it means retaining freshness history,
which is a producer change.

**For any other SLO** it means the series is short or has gone quiet —
investigate as a freshness problem first.

### 6 · `alts_cross_document_valid_rate` is below 100%

**Means:** some private-fund documents do not reconcile against the rest of
their fund — a commitment that does not continue, a call out of sequence, a
statement whose opening balance does not match the prior period's close.

**This is expected here.** The synthetic alts corpus carries deliberate
defects, so this rate sits around 60% by construction. It is the number that
gives the review queue something to review.

**Do:** work the queue in the internal app. A document with no confirmed values
is one gold is correctly declining to report (D-060), not a data error —
`alts_documents_unconfirmed_count` is queue depth, not a failure count.

**Escalate if:** the rate falls sharply with no new documents landed, which
would suggest the validation logic changed rather than the corpus.

### 7 · `fx_rate_stale_days_count` is above zero

**Means:** a rate was carried forward further than the ECB's own publication
calendar explains. The calendar never produces more than a 4-day carry, so this
is the tell for a rates feed that stopped rather than a holiday.

**First three checks:**
1. Did the daily Action's `fetch-fx` step run and land a new file?
2. `SELECT MAX(fx_rate_date), MAX(as_of) FROM workspace.parvum.gold_client_wealth` — how far behind is the newest published rate?
3. `SELECT * FROM workspace.parvum.dq_fx_plausibility WHERE stale ORDER BY as_of DESC` — which dates, and by how much?

**Do:** `make land-fx` to re-land the rates, then `make run-job`.

**Note:** a stale *local* copy of `data/reference/fx_rates.json` on a laptop
does not mean the lakehouse is stale — the daily Action lands its own. Check
the lakehouse before concluding anything.

## Routine operations

| Task | Command | Notes |
|---|---|---|
| Re-run the pipeline | `make run-job` | Idempotent. Always safe. Exceeds the CLI wait — see alert 2. |
| Re-land a day's feeds | `make land` | Overwriting a path does **not** fire the trigger (D-018); follow with `make run-job`. |
| Refresh reference data | `make land-fx`, `make land-registry`, `make land-restatements` | Reference overwrites deliberately do not trigger the job. |
| Reload the serving projection | Dispatch `export-gold.yml` in Actions | Not runnable from a laptop by design (D-039) — RDS credentials live only in CI. |
| Re-apply the metric views | `make metric-views` | Catalog objects, not Delta tables; the job does not build them. |
| Check the gate locally | `make check-governance` | Same check CI runs. |

## Two things that look broken and are not

- **Accuracy metrics at 1% and 34%.** Deliberate defect injection (D-011).
  Green there would mean the injector had stopped.
- **A flat stretch on the performance chart.** 13F prices are static within a
  filing regime; the boundary is marked on the chart for that reason.

## What is not covered here

No paging, no on-call rotation, no incident severities. Alerting is email plus
the freshness gate; the metrics-and-dashboards layer is Phase 8 on the
[roadmap](ROADMAP.md). Naming that gap is more useful than a runbook section
describing a rota that does not exist.
