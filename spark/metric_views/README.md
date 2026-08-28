# spark/metric_views/

The **semantic layer**: business measures defined once, in Unity Catalog, above
the physical tables — so SQL, BI, and an AI assistant all resolve a term the
same way instead of each re-expressing it. Full write-up with screenshots:
[`docs/SEMANTIC_LAYER.md`](../../docs/SEMANTIC_LAYER.md).

## What's here

| File | What it is |
|------|------------|
| `wealth_metrics.sql` | A Unity Catalog **metric view** over `gold_client_wealth`: a YAML spec of six measures and three dimensions, plus the `COMMENT` statements that carry each one's business definition. Stores no data. |
| `apply.py` | (Re)creates every `*.sql` here on the lakehouse via the SQL Statements API. |

A metric view is a **catalog object, not a Delta table**, so the bronze → gold
job (`databricks.yml`) does not build it. It is versioned here and applied on
its own.

## Applying it

```sh
make metric-views          # needs DATABRICKS_HOST (+ a token or cached CLI login)
```

or paste `wealth_metrics.sql` straight into the Databricks SQL editor.

## Querying it

Measures go through `MEASURE()`; dimensions are grouped normally. The
aggregation is fixed by the spec — a consumer chooses the grain and never
re-writes the `SUM`:

```sql
SELECT `Client`, MEASURE(`Total wealth`) AS aum
FROM   workspace.parvum.wealth_metrics
WHERE  `As of` = (SELECT MAX(as_of) FROM workspace.parvum.gold_client_wealth)
GROUP  BY `Client`
ORDER  BY aum DESC;
```

## AI/BI Genie

A Genie space ("Client Wealth Analytics") is pointed at this metric view.
Plain-language questions resolve to the *governed* measure and the answer cites
the view as its source — see `docs/SEMANTIC_LAYER.md`.
