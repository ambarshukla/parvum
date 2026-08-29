---
name: dataset-discovery-brief
description: Produce a stakeholder-facing brief on a table in the parvum lakehouse — what it is, what it can answer alone, what it cannot, what becomes answerable when combined, and how it is actually used. Use when someone asks "what is in this table", "can I use X to answer Y", or before building a report on a dataset nobody has explained.
---

# Dataset Discovery Brief

A schema tells someone what columns exist. It does not tell them what the data
*means*, what it can honestly answer, or — most importantly — what it cannot.
This skill produces the brief that closes that gap.

The section that earns the brief is **what you cannot learn from this alone**.
A dataset presented without its limits gets used past them, and the resulting
wrong answer is confident and traceable to nobody. Naming the limits up front
is the same discipline the CDE register applies to controls: an admitted gap is
manageable, an unstated one is a surprise.

## Before you start

Read these, in this order. They are the estate's own account of itself and
they will answer most of what you would otherwise guess:

1. `governance/cde_registry.yml` — the table's `context` (what it is *for*),
   its `grain`, its `foreign_keys` with cardinality, and per column its tier,
   owner, business definition, and either the quality rules that test it or a
   stated `control_gap`.
2. The `COLUMN_COMMENTS` dict in whichever `spark/*.py` publishes the table —
   the catalog description of every column, and the SQL that produces them.
3. `docs/ARCHITECTURE.md` for where the table sits in the medallion layering,
   and `docs/DECISIONS.md` for any D-number the register or comments cite.

If the table has a metric view in `spark/metric_views/`, read it too: the
measures there are the governed way to aggregate this data, and any measure the
view *declines* to expose is a deliberate signal (see `performance_metrics.sql`,
which refuses to expose returns because they are not additive).

## Calibrate the depth first

Ask what the brief is for before writing it. The failure mode is a thorough
brief nobody reads.

| Situation | Depth |
|---|---|
| "Can I use this for X?" | Phases 1–3 only. Two paragraphs and a verdict. |
| Someone is about to build a report on it | All seven phases. |
| A table with a critical element and an open `control_gap` | All seven, and lead with the gap. |
| Exploratory, no decision pending | Phases 1–2, and offer the rest. |

## The seven phases

### 1 · What this data *is*

One paragraph. What real-world event or state does one row represent? Quote the
register's `context` if it has one — it was written for exactly this. State the
`grain` explicitly and in words: *"one row per client per valuation date"*, not
`(as_of, client_id)`.

### 2 · What you can learn from it *alone*

Three to six questions this table answers on its own, with the column that
answers each. Be concrete — real question phrasings, not topics.

### 3 · What you **cannot** learn from it alone

The section that matters. Cover at least:

- **Questions it looks like it answers and does not.** A column named
  `total_wealth_usd` invites "what is total wealth" — but summing without
  pinning a date sums the whole series. Name traps like this explicitly.
- **Non-additive columns.** Rates, weights, indices and returns are correct at
  their own grain and meaningless summed. Say which columns these are.
- **Stated control gaps.** If the register records a `control_gap` on a column
  here, quote it. It is the estate's own admission that nothing checks that
  figure, and a consumer deserves to know before relying on it.
- **What the data is not.** Synthetic origin, deliberate defect injection
  (D-011), and any column that is forward-filled or prorated rather than
  observed.

### 4 · What becomes learnable when combined

Use the register's declared `foreign_keys`, including cardinality — a
`many_to_one` join can fan out and silently multiply a sum, and a reader
building an aggregate needs to know which joins do. For each: the join, and one
question it unlocks that neither table answers alone.

### 5 · How it is *actually* used today

Not how it could be used. Which dashboard tab, which API endpoint, which metric
view, which downstream table. Trace it: if a figure here appears on a client
screen, say which one. This is what stops a "harmless" change being made to a
column three surfaces depend on.

### 6 · Quality and service levels

What is measured about this data, from `dq_metrics` and `dq_slo_attainment`:
the metrics that test it, their current attainment, and — crucially — any that
are **breached by design** (`holdings_agreement` and `cash_ledger_integrity`
are, because the defect injector is doing its job; see `docs/RUNBOOK.md`). A
reader who sees a red number without that context draws the wrong conclusion.

### 7 · Who to ask

The register's `owner` role for these columns, and what that role is
accountable for. A role, not a person — that is what makes it durable.

## Rules

- **Never invent a definition.** If the register and the column comments do not
  say what something means, the brief says *"not documented — ask the owner"*.
  That sentence is a finding: it means a published column is not consumable,
  which is exactly what the gate's `missing_description` rule exists to
  prevent, and it should be reported rather than smoothed over.
- **Quote figures with their as-of date**, and re-read them live rather than
  copying them from a document. Numbers in this repo's prose go stale; the
  lakehouse does not.
- **Prefer the metric view over raw SQL** when one covers the question, and say
  so. That is the whole point of the semantic layer: one definition, consumed
  rather than re-derived.
- **Length follows the calibration above**, not the size of the table.
