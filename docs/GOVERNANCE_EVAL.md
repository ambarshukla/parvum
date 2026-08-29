# Does the governance metadata actually help an AI? — our own number

Every governance programme claims that better metadata produces better
analytics, and almost every one supports it with somebody else's number. This
is ours, measured on this estate, and built so it could come out unflattering.

Run it yourself: `parvum-governance-eval --provider anthropic`
(needs `DATABRICKS_HOST` and a provider key). Code and question set:
[`governance/src/parvum_governance/evaluation.py`](../governance/src/parvum_governance/evaluation.py).

## Method

Eight questions, each with a hand-written ground-truth SQL answer. Each is put
to the same model, at temperature 0, twice:

- **bare** — the table and column *names* only. What a warehouse with no
  metadata looks like from the outside.
- **governed** — the same names plus the catalog descriptions the Spark jobs
  publish, the register's business definitions for critical elements, and the
  semantic layer's measure definitions.

Both answers are executed against the real warehouse and compared with the
ground truth at the cent. An answer that runs and returns the wrong number
scores wrong — that is the interesting failure, because it looks like an
answer.

Every question has a trap that metadata can resolve and a schema cannot: a
grain that invites summing across dates, a term with a specific meaning here, a
controlled vocabulary. Questions a schema alone answers fine are not evidence
of anything and are left out. **That biases the test toward the cases where
metadata can matter, and the result should be read that way.**

## Result (2026-08-29, `claude-haiku-4.5`)

| | score |
|---|---|
| **bare** — column names only | **7 / 8 (88%)** |
| **governed** — with descriptions, definitions and measures | **8 / 8 (100%)** |

One question of eight. That is a much smaller gap than the figures usually
quoted for this kind of exercise, and reporting it honestly is the point of
having measured it at all.

## The one that failed, and why it is the whole story in miniature

> *"What is the total dividend income across all clients and all months?"*

```sql
-- bare: column names only
SELECT SUM(income_usd) AS answer FROM gold_income WHERE type = 'dividend'
-- -> no rows. No value.

-- governed: the column comment says "DIVIDEND or INTEREST"
SELECT SUM(income_usd) AS answer FROM gold_income WHERE type = 'DIVIDEND'
-- -> 306808.09
```

A schema says a `type` column exists. It does not say what values it takes. The
model guessed a reasonable-looking literal, matched nothing, and returned
nothing.

Note the failure mode: it produced **no answer**, not a confident wrong one.
That is the benign case. The dangerous one — a plausible number that is quietly
wrong — did not occur in this run, and saying so is more useful than implying
it did.

## Why this understates the value, and why that is not a complaint

The "bare" arm is not as bare as a real ungoverned warehouse. These column
names are clear — `total_wealth_usd`, `external_flow_usd`, `called_to_date_usd`
— and clear names carried most of the load. But they are clear *because* the
same discipline that produced the register produced the naming: the gate has
required every published column to carry a description since D-067, and you
cannot write a description for a badly-named column without noticing.

So the honest reading is not "metadata is worth 12 points". It is:

> On an estate where naming is already disciplined, explicit metadata closes
> the remaining gap — and the remaining gap is concentrated in exactly the
> places a name cannot reach: controlled vocabularies, grain, and terms with a
> local meaning.

The 21%→95% figures quoted at conferences are measured on estates where the
naming is *not* disciplined. Both numbers can be true.

## Limits

Stated plainly, because a small eval presented as a benchmark is worse than no
eval:

- **Eight questions.** One flipped answer moves the score by 12.5 points.
- **One model, one temperature, one estate.** This generalises to nothing.
- **The questions were written by the person who built the metadata**, which is
  a real bias. Each one records the trap it is testing so a reader can judge
  whether it is fair rather than taking that on trust.
- **Ground truth is hand-written SQL**, so it is only as correct as the person
  who wrote it. It is checkable: the queries are in the question set.
