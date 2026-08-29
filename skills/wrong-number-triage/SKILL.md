---
name: wrong-number-triage
description: Investigate a figure that looks wrong on a screen or in a table — the method this project derived from three real defects that reached a live dashboard. Use when a number is questioned, a metric moved unexpectedly, or two figures that should agree do not.
---

# Wrong-number triage

Three defects reached a live client dashboard in this project. Every one was
found by a person looking at a screen, not by a control, and every one had the
same shape:

> **Every figure was individually correct, and two figures disagreed about what
> had happened.**

- **D-070** — a share-divisor change rescaled a book fivefold; the performance
  chain read it as market movement and reported **+392.70%** since inception.
- **D-072** — a fully-loaded NAV over a partially-confirmed denominator gave
  private-fund multiples of **4.13× to 4.65×**.
- **D-073** — the class of check that would have caught both was missing
  entirely: everything validated a number against *its own* source, nothing
  compared two published numbers.

This skill is that experience as a procedure.

## Step 0 — establish what the number should be, before touching anything

Get the figure, its as-of date, and the surface it appeared on. Then compute
the same thing from the lakehouse independently. **Do not read the value from
the same table the screen read it from** — that confirms the pipeline is
self-consistent, which is rarely the question.

If the two agree, the defect is upstream of the surface. If they differ, it is
in the projection or the front end, and D-071 is the precedent: the exporter
selects every column and inserts by name, so producer and consumer must move
together.

## Step 1 — is it wrong, or is it surprising?

Distinguish these before spending an hour. Real things in this estate that look
broken and are not:

| Looks wrong | Actually |
|---|---|
| A long flat stretch on the performance chart | 13F prices are static within a filing regime; the boundary is marked |
| Accuracy metrics at 1% and 34% | Deliberate defect injection (D-011). Green would mean the injector stopped |
| Two SLOs permanently breached | Same reason — see `docs/RUNBOOK.md` |
| A client's wealth stepping on a quarter boundary | A new 13F filing landed; the book steps |
| Alts NAV unchanged for weeks | Forward-filled from the last *confirmed* statement (D-060) |
| IRR differing sharply from TWR | Expected over short periods — `docs/PERFORMANCE_METHODOLOGY.md` |

## Step 2 — the diagnostic question

Ask this before forming any theory:

> **Does this number move when the thing it claims to measure has not moved?**

That single question found D-072. The multiple tracked *review progress* — a
fund with two of four notices confirmed read 1.90×, everything else 4.13–4.65×
— which meant **approving a pending capital call would make performance look
worse**. A metric that moves when nothing about the underlying moved is not a
metric of the underlying.

Apply it concretely: list what changed in the window. A deploy, a reference-data
change, a human review decision, a new filing. If the figure moved and none of
those touch what it measures, the figure is measuring something else.

## Step 3 — check the adjacent columns

Wrong numbers here have twice been visible for weeks as an arithmetic
disagreement nobody added up. Before anything sophisticated:

- Do the parts sum to the whole? (`positions + cash + alts` vs `total_wealth_usd`)
- Do the splits reconcile? (`called + unfunded` vs `total_commitment` — this was
  wrong for weeks and unread)
- Do two aggregation paths agree? (`gold_asset_allocation` vs
  `gold_client_wealth` reconstruct the same total at different grains)
- Does the badge match its own drill-down? (`reconcile_variance_usd` vs
  `gold_reconciliation_exceptions`)

`dq_cross_field_invariants` now asserts these daily. **Query it first** — if an
invariant is already failing, the investigation is largely done.

## Step 4 — same moment, same document

D-072's root cause: gold's "only confirmed values count" rule was applied *per
document type independently*, so a numerator embedding every capital call sat
over a denominator counting only confirmed notices.

So: **for any ratio or difference, check every term comes from the same source
and the same as-of moment.** Write them out side by side with their provenance.
A ratio assembled from two moments is wrong even when both moments are right.

## Step 5 — is the unit the same on both sides?

D-070's root cause: the book was rescaled, so 16 August and 17 August were
denominated in different rulers, and a ratio across the boundary measured the
change of ruler. Check for restatements, divisor changes, currency changes and
unit changes across any period boundary. `book_restatements.json` and
`gold_performance.restatement_detail` record the declared ones.

## Step 6 — write the fix as a control, not just a correction

A corrected number leaves the next instance undetected. Ask what check would
have caught this, and be honest about whether it really would:

- **D-070's lesson:** the register had already flagged those columns and
  proposed the *wrong* remedy — independent recomputation, which would have
  reproduced the wrong figure faithfully, because the formula was never wrong.
  "The register predicted this" did not survive scrutiny and was not claimed.
- **D-073's lesson:** the best checks need no theory of what will break them.
  "A commitment splits into called and unfunded" is knowledge a business
  analyst has on day one, and it catches a bug nobody has thought of yet.
- **The citation test:** before claiming a check covers a column, ask *which
  specific row of this check fails if this column is wrong?* If there is no
  answer, it is a loosely-related metric wearing the costume of a control, and
  citing it inflates coverage while testing nothing.

## Step 7 — record it honestly

A decision entry in `docs/DECISIONS.md`: what was wrong, why nothing caught it,
what was chosen, what was rejected, and any part of the earlier story that did
not survive investigation. D-072 records that the "obvious" contradiction the
user suspected did not exist — and that chasing it found a real defect anyway.
Both halves belong in the record.
