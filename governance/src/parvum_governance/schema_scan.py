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

# Table-name prefix -> medallion layer. The prefix is the naming contract the
# whole lakehouse already follows (bronze_file_registry, silver_positions,
# dq_metrics, gold_client_wealth), so deriving the layer from it needs no
# second source of truth to keep in step.
LAYER_PREFIXES = {
    "bronze_": "bronze",
    "silver_": "silver",
    "dq_": "dq",
    "gold_": "gold",
    # Governance publishes a table too — the register itself. It is subject
    # to its own rule: the columns below have to be classified in the very
    # file they describe, or the gate blocks the merge.
    "governance_": "governance",
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
    """Medallion layer for a table name, from its prefix.

    An unrecognised prefix is an error rather than an "other" bucket: a new
    layer is a real architectural event and should be a deliberate edit here,
    not something that silently lands in a catch-all.
    """
    for prefix, layer in LAYER_PREFIXES.items():
        if table.startswith(prefix):
            return layer
    raise SchemaScanError(
        f"table {table!r} has no recognised layer prefix (expected one of {sorted(LAYER_PREFIXES)})"
    )


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
_METRIC_PATTERN = re.compile(r"'([a-z0-9_]+)'\s+AS\s+metric", re.IGNORECASE)
_MIN_DQ_METRICS = 4


def scan_dq_metric_names(dq_job: Path) -> set[str]:
    """Every metric name `dq_metrics` publishes, read from the job that builds it."""
    names = set(_METRIC_PATTERN.findall(dq_job.read_text(encoding="utf-8")))
    if len(names) < _MIN_DQ_METRICS:
        raise SchemaScanError(
            f"{dq_job.name}: found only {len(names)} metric names "
            f"({sorted(names)}) — the `'<name>' AS metric` shape this scan "
            f"depends on has probably changed, and the gate would wrongly "
            f"reject every quality rule the register cites"
        )
    return names
