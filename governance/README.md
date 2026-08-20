# governance/

The governance layer, as its own package (`parvum-governance`): the
register of what this platform publishes and who is accountable for it,
plus the gate that keeps the register honest.

- `cde_registry.yml` — the **Critical Data Element register**. One entry
  per published column: its tier, its owner, and — for critical elements
  — a business definition, a named service level, and either the quality
  rules that test it or a stated gap where none exists yet.
- `schema_scan.py` — reads the real column inventory out of the Spark
  jobs' `COLUMN_COMMENTS` dicts, and the DQ metric names out of the SQL
  that builds `dq_metrics`. Parsing (`ast`), not importing: those files
  are Databricks notebooks that call `spark.sql` at module scope.
- `registry.py` — loads the register and holds the tier obligations.
- `check.py` — the five gate rules that reconcile the two.
- `cli.py` — `parvum-check-governance`, run by CI and by `make
  check-governance`.

## Why this is a package and not a folder

Governance depends on nothing else in the workspace, and nothing in the
workspace depends on it. It *reads* the pipeline and judges it — which is
the relationship a control should have to the thing it controls, and the
reason it has its own CI status check rather than sharing one.

## What the gate enforces

A pull request fails if it leaves the register and the platform out of
step:

| rule | fires when |
| --- | --- |
| `unclassified` | a column reaches the catalog with no register entry |
| `orphan` | the register describes a column no job publishes any more |
| `missing_description` | a published column carries no catalog comment |
| `incomplete_obligation` | a tier's obligations are unmet (a critical element with no owner, definition, SLO, or statement about controls) |
| `invalid_reference` | the register points at an unknown owner, tier, SLO, or a quality rule the DQ layer does not compute |

The tiers themselves are defined in `registry.py`, deliberately not in
the YAML: a register able to relax its own rules would not be a control.

Adding a column is always allowed. Declining to say who owns it, and how
much it matters, is not.
