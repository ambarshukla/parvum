# governance/

The governance layer, as its own package (`parvum-governance`): the
register of what this platform publishes and who is accountable for it,
plus the gate that keeps the register honest.

- `cde_registry.yml` — the **Critical Data Element register**. One entry
  per published column: its tier, its owner, and — for critical elements
  — a business definition, a named service level, and either the quality
  rules that test it or a stated gap where none exists yet. Tables also
  declare their **contracts**: the `grain` one row represents, the
  `foreign_keys` that join them to the rest of the estate (with
  cardinality), and a `context` sentence saying what the table is *for*.
- `schema_scan.py` — reads the real column inventory out of the Spark
  jobs' `COLUMN_COMMENTS` dicts, and the DQ metric names out of the SQL
  that builds `dq_metrics`. Parsing (`ast`), not importing: those files
  are Databricks notebooks that call `spark.sql` at module scope.
- `registry.py` — loads the register and holds the tier obligations.
- `check.py` — the five gate rules that reconcile the two.
- `cli.py` — `parvum-check-governance`, run by CI and by `make
  check-governance`; and `parvum-publish-registry`, which writes the
  landable snapshot.
- `publish.py` — resolves the register against the live column scan into
  JSON Lines for the lakehouse (`make land-registry`). One record per
  column the platform *publishes*, so coverage can be computed from the
  rows rather than asserted. Refuses to write if the gate fails.
- `metric_views.py` — reads the semantic layer's declared measures and their
  business definitions out of `spark/metric_views/*.sql`, so the gate can
  govern the measures too, not only the columns.
- `evaluation.py` — `parvum-governance-eval`: does any of this actually help
  an AI? Eight questions asked twice, with column names alone and with the
  full metadata, both executed against the warehouse and scored against
  hand-written ground truth. Our own number rather than someone else's; see
  `docs/GOVERNANCE_EVAL.md`.

## Why this is a package and not a folder

Governance depends on nothing else in the workspace, and nothing in the
workspace depends on it. It *reads* the pipeline and judges it — which is
the relationship a control should have to the thing it controls, and the
reason it has its own CI status check rather than sharing one.

## What the gate enforces

A pull request fails if it leaves the register and the platform out of
step, or leaves a promise nobody is on the hook for:

| rule | fires when |
| --- | --- |
| `unclassified` | a column reaches the catalog with no register entry |
| `orphan` | the register describes a column no job publishes any more |
| `missing_description` | a published column carries no catalog comment |
| `incomplete_obligation` | a tier's obligations are unmet (a critical element with no owner, definition, SLO, or statement about controls) |
| `invalid_reference` | the register points at an unknown owner, tier, SLO, or a quality rule the DQ layer does not compute |
| `unheld_slo` | a service level is declared but no critical element is held to it — the mirror of `orphan`, and, since attainment is computed from the SLOs elements cite, an unheld one is never measured either |
| `broken_contract` | a declared grain or foreign-key column the table does not publish, a foreign key pointing at a column no job publishes, an unknown join cardinality, or a table with a critical element and no narrative `context` |

The tiers themselves are defined in `registry.py`, deliberately not in
the YAML: a register able to relax its own rules would not be a control.

Adding a column is always allowed. Declining to say who owns it, and how
much it matters, is not.

**Why the contracts live here rather than in a catalog comment.** Join keys,
cardinality and "what is this table for" are exactly the metadata an analyst
or a model needs, and they are conventionally written into column comments —
where they read as authoritative and nothing ever checks them. They rot the
first moment a column is renamed, and the reader has no way to tell. Declared
here, both ends of every join resolve against the columns the Spark jobs
actually publish, so a contract that stops being true fails the build.

## Where it shows up downstream

`spark/dq_recon.py` reads the landed snapshot into `governance_cde_registry`
and rolls four metrics into `dq_metrics` under a `governance` dimension:
`columns_classified_rate`, `critical_control_coverage_rate` (against a stated
80% target — set when the estate delivered 35.7% and unmoved since; the estate
crossed it at D-073), `critical_element_count` and `control_gap_count`. See
D-068.

Each named service level also carries the machine-readable half of its
objective (`attainment_objective`, `window_days`), which is what lets
`spark/gold_reports.py` compute `dq_slo_attainment` — attainment and error-budget
consumption per SLO — without a second landed file to keep in step. See D-075,
and `docs/RUNBOOK.md` for what a breach obliges an operator to do.

Note the recursion: `governance_cde_registry` is a published table, so the
register has to classify its own columns. The gate enforces that like any
other table.
