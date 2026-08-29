# Personas — who this platform is for, and how each one gets served

A platform with one surface serves one person. This one has four surfaces
because it has four kinds of user, and they want incompatible things: a client
wants a number and a sentence; an operator wants the row that broke; an analyst
wants to ask a question nobody anticipated; an engineer wants the definition in
version control.

Naming them is not decoration. It is what stops "add it to the dashboard"
being the answer to every request — the reflex that turns one screen into a
control panel nobody can read.

## The four

| Persona | Who they are | Primary surface | Enablement path | Self-serve ceiling |
|---|---|---|---|---|
| **Consumer** | The client, or an advisor reading on their behalf. Wants their position and whether to trust it. | [Client dashboard](https://parvum-dashboard.vercel.app) — seven tabs, no login | Nothing to learn. Every verdict on the screen is clickable through to the figures behind it (D-065). | Cannot ask a new question. By design: an unanticipated question from this persona is a request for a new tab, not a query tool. |
| **Producer** | Whoever owns a feed, a table, or a control. Today: me. In an organisation: the publishing team. | The repo — `governance/cde_registry.yml`, the Spark jobs, the CI gate | A new column fails the build until it is classified (D-067). The obligation is enforced at the moment of publishing, not audited afterwards. | High: the register, the gate, the metric-view specs, and the DQ checks are all one PR each. |
| **Operator** | Whoever is on the hook when the pipeline misbehaves overnight. | [Internal app → Ops](https://parvum-internal.vercel.app/?demo=1) + [`RUNBOOK.md`](RUNBOOK.md) | The runbook names, per alert: what it means, the first three checks, and when to escalate. The Ops page shows service levels, attainment, and the gap list. | Can diagnose and decide without reading the code. Cannot fix a broken feed — that escalates to the producer. |
| **Analyst** | Someone with a question the dashboard does not answer. | [AI/BI Genie space + metric views](SEMANTIC_LAYER.md), and SQL over the lakehouse | Plain-language questions resolve to *governed* measures (D-074), so an answer cannot quietly disagree with the dashboard. `MEASURE()` for anyone writing SQL directly. | High for anything the metric views cover; drops to raw SQL beyond them — which is the honest limit of the current semantic layer. |

An **executive** reader is deliberately not a fifth persona here. In a larger
organisation they would be — the summary-and-exception view is a real and
distinct need. At this size they are a consumer of the Ops page's top tiles and
the client dashboard's headline; inventing a separate surface for an audience of
none would be architecture theatre.

## Why the alts review queue is the operator's, not the analyst's

The review queue looks like an analyst tool — it shows an extracted document
and asks for judgement. It is on the operator surface because the judgement is
*operational*: this document either passes into the books or it does not, and
the queue is a work list with a service level, not an exploration. Analysts ask
"what is true?"; operators answer "is this ready to publish?".

## What each persona is promised

- **Consumer** — a figure with its provenance reachable in one click, and
  visible exclusion of anything not yet confirmed (D-060). Never a number
  that quietly averages over a gap.
- **Producer** — the platform refuses work that skips the obligation. No
  chasing, no spreadsheet, no governance team filing tickets.
- **Operator** — every alert resolves to a named runbook entry, and every
  service level has a stated target, a measured attainment, and an error
  budget (D-075).
- **Analyst** — an answer that agrees with the dashboard *by construction*,
  because both resolve the same governed measure.

## Known gaps

Stated, not fixed:

- **The analyst path covers one metric view.** `wealth_metrics` covers client
  wealth; allocation, performance, income and alts are reachable only as raw
  tables. An analyst asking about performance today is outside the governed
  vocabulary.
- **No per-persona access control.** The internal app has one password and one
  role; a real deployment would separate operator from producer.
- **The producer path assumes one producer.** Ownership is by *role* in the
  register (which is the property that survives people changing jobs), but
  there is no routing, no notification, and no way for an owner to acknowledge
  a gap assigned to them.
