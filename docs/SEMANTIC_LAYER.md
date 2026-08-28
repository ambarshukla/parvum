# Semantic layer — governed measures and AI/BI

Gold hands every consumer the same tables. It does not hand them the same
**definitions**: "total wealth" is `SUM(total_wealth_usd)` grouped the right
way, and every dashboard, notebook, and ad-hoc query re-expresses that by hand.
A semantic layer lifts the definition up into Unity Catalog, once, so SQL, BI,
and an AI assistant all resolve the term identically.

This is the layer above the [CDE register](../governance/cde_registry.yml):
the register classifies every published *column* and a CI gate keeps it honest;
the semantic layer names the *measures* a person actually asks for and binds
each to a governed column.

## The metric view

`workspace.parvum.wealth_metrics` is a Unity Catalog **metric view** — a YAML
spec of dimensions and measures over a single source table
(`gold_client_wealth`). It stores no data; it is a governed query surface. Six
measures, three dimensions, each carrying a column comment that is the
*business* definition, not the technical one.

![The wealth_metrics metric view in Catalog Explorer: description, six measures with comments, three fields](img/metric-view-wealth-metrics.png)

The definition lives in the repo at
[`spark/metric_views/wealth_metrics.sql`](../spark/metric_views/wealth_metrics.sql)
and is applied with `make metric-views` (or pasted into the SQL editor). A
metric view is a catalog object, not a Delta table, so the bronze → gold job
does not create it — it is versioned and re-applied on its own.

### Querying it

Measures are referenced through `MEASURE()`; dimensions are grouped normally.
The aggregation is fixed by the spec, so a consumer picks the grain and never
re-writes the `SUM`:

```sql
SELECT `Client`, MEASURE(`Total wealth`) AS aum
FROM   workspace.parvum.wealth_metrics
WHERE  `As of` = (SELECT MAX(as_of) FROM workspace.parvum.gold_client_wealth)
GROUP  BY `Client`
ORDER  BY aum DESC;
```

![The MEASURE() query in the Databricks SQL editor returning three client rows](img/metric-view-query.png)

## It is lineage-tracked

Unity Catalog treats the metric view like any other object. `gold_client_wealth`
shows it downstream, alongside the Genie space that reads it, and the silver
tables the gold table is built from upstream — the semantic layer is inside the
lineage graph, not bolted onto its edge.

![Lineage view of gold_client_wealth showing the metric view and Genie agent downstream, silver tables upstream](img/metric-view-lineage.png)

## AI/BI Genie over the layer

A Genie space ("Client Wealth Analytics") is pointed at the metric view. A
plain-language question resolves to the **governed** measure — not an
aggregation the model reinvented — and the answer cites the metric view as its
source.

![Genie answering "total wealth by client for the latest date" with a bar chart, citing the metric view as source](img/genie-total-wealth.png)

The next question crosses from the headline number into the data-quality
columns on the same view — one vocabulary for both.

![Genie answering "which clients' books don't reconcile" with a per-client breakdown](img/genie-reconciliation.png)

## Why this is the governance story, not a BI feature

An AI assistant reading this layer inherits the four properties a new analyst
needs before they can use a dataset unaided — **lineage** (Unity Catalog tracks
it), **schema** (the spec is explicit), a **quality signal** (the same view
exposes `Books reconcile` and `Reconcile variance`), and a **definition** of
each term (the column comments). That set is the whole content of
"AI-ready" — which is why the semantic-layer work and the governance work are
the same work.

It sits on top of a live pipeline: `gold_client_wealth` is rebuilt by the
`parvum-ingest` job on every custodial-feed arrival, so the measures move when
the data does.

![parvum-ingest run history — bronze, silver, silver_cash, dq_recon, gold, all green](img/pipeline-run-history.png)

## Limits (Free Edition, and honest scope)

- The metric view's measures are not themselves in the CDE register yet; they
  inherit classification from their source columns. Bringing the semantic layer
  under the same gate is a natural extension, not done here.
- The Genie space is configured in the workspace; the metric view it reads is
  in git, its instruction text is not.
- Free Edition provides a single serverless warehouse with daily usage limits —
  this is a reference-scale deployment, not a capacity test.
