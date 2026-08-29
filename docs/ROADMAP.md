# Roadmap

**Reviewed quarterly.** Last reviewed **2026-08-29** (Q3 2026) · next review
**2026-10-01** (Q4 2026).

A roadmap nobody revisits is a wish list. The review is a fixed date, the
changelog at the bottom records what actually moved, and items that were
dropped stay visible as dropped rather than quietly disappearing.

Design decisions behind each item live in [DECISIONS.md](DECISIONS.md); the
narrative of what happened is in [BUILD_LOG.md](BUILD_LOG.md).

## How to read this

| Status | Means |
|---|---|
| ✅ done | Merged, and verified against live data |
| 🔶 in progress | Partly shipped; the remainder is named below it |
| ⬜ planned | Committed to, not started |
| 🅿️ parked | Deliberately not doing now, with the trigger that would revive it |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundations — repo, local Postgres, docs | ✅ done |
| 1 | Custodial feed ingestion → Bronze (semt.002, MT535, camt.053) | ✅ done |
| 2 | Reference data & normalisation → Silver | ✅ done |
| 3 | Reconciliation & data-quality control | ✅ done |
| 4 | Portfolio aggregation & ownership graph → Gold | ✅ done |
| 5 | Java serving layer (Quarkus + jOOQ) + live site | ✅ done |
| 6 | Alternatives HITL pipeline | ✅ done |
| 7 | Infrastructure as code — Terraform (RDS, ECS Express Mode, ECR) | ✅ done |
| 8 | Observability stack — metrics, dashboards, paging | 🔶 in progress |
| 9 | Data governance — CDE register, publisher-obligation gate, service levels, semantic layer | 🔶 in progress |

## Q3 2026 — current focus

Phase 9, the governance and AI-readiness layer. The ordering principle has been
**enforcement before description**: build the thing that can fail a change
first, then make it visible, then make it consumable.

| Item | What it is | Status |
|---|---|---|
| CDE register + publisher-obligation gate | Every published column classified and owned; a CI check that fails a PR which skips the obligation | ✅ done (D-067) |
| Register into the lakehouse | Coverage as a daily, queryable metric beside freshness and accuracy | ✅ done (D-068) |
| Governance on a screen | Ops page section, leading with the gaps rather than the score | ✅ done (D-069) |
| Cross-field invariants | Assert that published figures which describe the same fact agree | ✅ done (D-073) |
| Semantic layer | Metric views: each business measure defined once, consumed by SQL, BI and AI/BI Genie | ✅ done (D-074) |
| Persona architecture | Named personas, each with a surface and an enablement path — [PERSONAS.md](PERSONAS.md) | ✅ done (D-076) |
| Published roadmap | This document, on a quarterly cadence | ✅ done (D-076) |
| Named SLOs with attainment + error budgets | Promote implicit thresholds to declared service levels that are *measured*, not just stated | ✅ done (D-075) |
| Operator handoff standard | [RUNBOOK.md](RUNBOOK.md) — per alert: what it means, first checks, escalation | ✅ done (D-075) |
| Column contracts in the register | Declared foreign keys and join cardinality, **verified** by the gate rather than described in a comment | ⬜ planned |
| Close the two remaining control-gap root causes | The alts chain's validation rolling up into `dq_metrics`; a landed FX rate re-checked against source | ⬜ planned |
| Semantic layer beyond one table | Metric views for allocation, performance and income; their measures brought under the gate | ⬜ planned |
| Governance eval | Measure answer accuracy with vs. without the register and semantic layer — our own number | ⬜ planned |

## Q4 2026 — next

| Item | Why it follows |
|---|---|
| Finish Phase 8 observability | Service levels (Q3) give paging something to page *on*. Sequencing that the other way produces alerts nobody can action. |
| Analyst self-serve beyond the metric views | Only worth building once the governed vocabulary covers more than client wealth. |
| Per-persona access control on the internal app | One password and one role today; splitting operator from producer is real work, not config. |

## Parked

| Item | Why | What would revive it |
|---|---|---|
| Gold alts metrics (DPI / TVPI / J-curve) | The alts *chain* is complete and demonstrates the hard part (extraction → validation → human review → reverse sync). More fund-maths is breadth, not depth. | A conversation that needs the private-markets reporting story rather than the pipeline story. |
| External dead-man's switch | The freshness gate catches "the job stopped producing". Nothing catches "the whole account is gone" — but that needs infrastructure outside this account to be worth anything. | Any dependency on this running unattended for longer than a demo. |
| 13F-HR/A amendment handling | A faithful point-in-time store would supersede an original from the amendment's own filing date. Recorded backlog, not oversight. | A restatement scenario where the amendment path is the point. |
| Multi-region deployment | Schema-per-tenant already proves the repeatable-onboarding shape; a second AWS region proves nothing new and doubles the bill. | A cost budget that makes it free, or a latency argument. |

## Explicitly not doing

Worth stating, because "not yet" and "never" are different commitments:

- **Real client data.** Custodial feeds and private-fund documents are
  confidential. The formats are real, the 13F holdings underneath are real,
  the data is synthetic, and that boundary is permanent.
- **Production-scale tuning.** This runs on Databricks Free Edition. What the
  architecture would do at 1000× is written up in reasoning, not benchmarked —
  and claiming otherwise would be the easiest lie in the repo to tell.
- **A second orchestrator.** GitHub Actions fetches, Databricks processes. The
  split exists because of an egress constraint (D-006) and has earned its keep;
  adding Airflow would be résumé-driven.

## Changelog

| Date | Change |
|---|---|
| 2026-08-29 | First published. Q3 governance items recorded; SLO attainment, column contracts, control-gap closure, semantic-layer expansion and the governance eval carried into the remainder of the quarter. |
