"""Read the published column inventory straight out of the Spark jobs.

Every Spark job in `spark/` ends with a `COLUMN_COMMENTS` dict that it
applies to Unity Catalog as `ALTER TABLE ... ALTER COLUMN ... COMMENT`. That
dict is therefore the authoritative statement of what columns this platform
publishes and what each one means — the catalog is downstream of it, not the
other way round.

The governance gate has to check the register against *that* inventory rather
than against a hand-maintained copy, or the register quietly rots the first
time somebody adds a column. So this module parses the job files.

Parsing, not importing: these files are Databricks notebooks. They call
`spark.sql(...)` at module scope against a `spark` session that only exists
inside a cluster, so importing one outside Databricks fails immediately.
`ast.literal_eval` over the parsed source gets the dict without executing a
line of it — which also means a job can never make the gate do something
surprising at check time.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# The lakehouse names every table `<layer>.<name>` — the medallion layer is
# the Unity Catalog schema it lives in (`parvum.gold.client_wealth`), and the
# jobs key their `COLUMN_COMMENTS` dicts by that same `<layer>.<name>`. So the
# layer needs no second source of truth: it is the first path segment.
LAYERS = {
    "bronze",
    "silver",
    "dq",
    "gold",
    # Governance publishes a table too — the register itself. It is subject
    # to its own rule: the columns below have to be classified in the very
    # file they describe, or the gate blocks the merge.
    "governance",
}


class SchemaScanError(RuntimeError):
    """A Spark job could not be read for its column inventory."""


@dataclass(frozen=True)
class PublishedColumn:
    """One column this platform publishes, as declared by the job that writes it."""

    table: str
    column: str
    description: str
    layer: str
    source_file: str

    @property
    def key(self) -> str:
        """`table.column` — how the register addresses a column."""
        return f"{self.table}.{self.column}"


def layer_for(table: str) -> str:
    """Medallion layer for a table identifier — the schema it sits in.

    Identifiers are `<layer>.<name>` (`gold.client_wealth`). An unrecognised
    layer is an error rather than an "other" bucket: a new schema is a real
    architectural event and should be a deliberate edit to `LAYERS` above, not
    something that silently lands in a catch-all.
    """
    layer, _, name = table.partition(".")
    if not name or "." in name:
        raise SchemaScanError(f"table {table!r} is not a `<layer>.<name>` identifier")
    if layer not in LAYERS:
        raise SchemaScanError(
            f"table {table!r} has an unrecognised layer (expected one of {sorted(LAYERS)})"
        )
    return layer


def extract_column_comments(source: str, *, origin: str) -> dict[str, dict[str, str]]:
    """Pull the `COLUMN_COMMENTS` literal out of one Spark job's source."""
    tree = ast.parse(source, filename=origin)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "COLUMN_COMMENTS"
            for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError as exc:
            # A computed comment (an f-string, a concatenation, a lookup)
            # would make the inventory unknowable without running the job.
            raise SchemaScanError(
                f"{origin}: COLUMN_COMMENTS is not a plain literal — "
                f"the governance gate can only read constant descriptions ({exc})"
            ) from exc
        if not isinstance(value, dict):
            raise SchemaScanError(f"{origin}: COLUMN_COMMENTS is not a dict")
        return value
    raise SchemaScanError(f"{origin}: no COLUMN_COMMENTS assignment found")


def scan_job(path: Path) -> list[PublishedColumn]:
    """Every column one Spark job publishes."""
    comments = extract_column_comments(path.read_text(encoding="utf-8"), origin=path.name)
    columns: list[PublishedColumn] = []
    for table, table_comments in sorted(comments.items()):
        if not isinstance(table_comments, dict):
            raise SchemaScanError(f"{path.name}: {table!r} does not map to a dict of columns")
        for column, description in table_comments.items():
            columns.append(
                PublishedColumn(
                    table=table,
                    column=column,
                    description=description,
                    layer=layer_for(table),
                    source_file=path.name,
                )
            )
    return columns


def scan_spark_jobs(spark_dir: Path) -> list[PublishedColumn]:
    """Every column the whole platform publishes, across all Spark jobs.

    Jobs with no `COLUMN_COMMENTS` at all are skipped rather than failing: a
    job that writes no table (a pure orchestration or check notebook) is a
    legitimate thing to have. A job that *has* the dict but in a shape we
    cannot read is still an error, because that is drift, not absence.
    """
    columns: list[PublishedColumn] = []
    for path in sorted(spark_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "COLUMN_COMMENTS" not in source:
            continue
        columns.extend(scan_job(path))

    duplicates = _duplicate_keys(columns)
    if duplicates:
        # Two jobs describing the same column would give the register two
        # different descriptions to satisfy, and the gate no single answer.
        raise SchemaScanError(f"columns declared by more than one job: {', '.join(duplicates)}")
    return columns


def _duplicate_keys(columns: list[PublishedColumn]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for column in columns:
        if column.key in seen:
            duplicates.add(column.key)
        seen.add(column.key)
    return sorted(duplicates)


# The DQ layer names its metrics inline in the SQL that builds `dq_metrics`,
# as `'<name>' AS metric`. A quality rule cited by the register has to name
# one of those, so the gate needs the list — and again cannot import the job
# to ask it. A regex over the SQL is the honest tool here; `_MIN_DQ_METRICS`
# below turns "the SQL got restructured and we now match nothing" from a
# silently-passing gate into a loud failure.
#
# More than one job contributes: `dq_recon` builds the table, and `gold_reports`
# appends the rows only it can compute, because gold runs after dq_recon and a
# metric derived from gold would otherwise report the previous run's numbers
# (D-070). Every contributing file must yield at least one name, so a job that
# stops publishing metrics fails loudly here rather than quietly shrinking the
# vocabulary the register is checked against.
_METRIC_PATTERN = re.compile(r"'([a-z0-9_]+)'\s+AS\s+metric", re.IGNORECASE)
_MIN_DQ_METRICS = 4


def scan_dq_metric_names(*dq_jobs: Path) -> set[str]:
    """Every metric name `dq_metrics` publishes, read from the jobs that write it."""
    if not dq_jobs:
        raise SchemaScanError("no metric-publishing jobs given to scan")

    names: set[str] = set()
    for job in dq_jobs:
        found = set(_METRIC_PATTERN.findall(job.read_text(encoding="utf-8")))
        if not found:
            raise SchemaScanError(
                f"{job.name}: publishes no `'<name>' AS metric` rows — either it "
                f"stopped writing dq_metrics or the shape this scan depends on "
                f"changed; both need a look before the gate is trusted"
            )
        names |= found

    if len(names) < _MIN_DQ_METRICS:
        raise SchemaScanError(
            f"found only {len(names)} metric names across "
            f"{[job.name for job in dq_jobs]} ({sorted(names)}) — the "
            f"`'<name>' AS metric` shape this scan depends on has probably "
            f"changed, and the gate would wrongly reject every quality rule "
            f"the register cites"
        )
    return names
