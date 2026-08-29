"""Publish the register as a landable snapshot for the lakehouse.

The register is a YAML file in the repo, which is the right home for it: an
ownership change should be a reviewable diff. But a register nobody can query
is a register nobody consults, so the lakehouse needs a copy — and the
lakehouse's own contract for outside data is the one every reference feed
already uses: a file lands in the volume, a Spark job reads it (D-006, no
egress from the cluster).

So this writes JSON Lines, one record per **published** column, resolved:
every field the register says about it, flattened, plus the catalog
description the Spark job publishes for it. Not one record per *registered*
column — publishing what the platform actually emits means the lakehouse can
compute its own classification coverage from the rows themselves rather than
being told a number. The gate keeps that at 100%; the metric proves it
instead of asserting it.

Two shape choices worth naming:

* **`quality_rules` is a comma-joined string, not an array.** A Delta array
  is the truer type, but this table's whole purpose is to be read — through
  the exporter, into Postgres, onto a screen — and an array type stops the
  exporter's wire-format conversion dead. `quality_rule_count` carries the
  one thing the flattening would otherwise cost: counting without parsing.
* **The SLO is flattened into the row** (`slo`, `slo_measured_by`,
  `slo_target`, and since D-075 the machine-readable
  `slo_attainment_objective` / `slo_window_days`) rather than referenced. One
  table that answers a question is worth more here than two that need
  joining — and it means the gold layer can derive the SLO set it must
  measure attainment for from this one landed file, with no second feed to
  keep in step.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from parvum_governance.registry import Registry, load_registry
from parvum_governance.schema_scan import scan_spark_jobs

#: Where the landed copy lives, on both sides of the boundary.
LOCAL_SNAPSHOT = Path("data/reference/cde_registry.json")
VOLUME_SNAPSHOT = "/Volumes/workspace/parvum/landing/reference/cde_registry.json"


@dataclass(frozen=True)
class SnapshotRow:
    """One published column, with whatever the register says about it."""

    table_name: str
    column_name: str
    layer: str
    description: str
    tier: str | None
    owner: str | None
    definition: str | None
    quality_rules: str
    quality_rule_count: int
    control_gap: str | None
    slo: str | None
    slo_objective: str | None
    slo_measured_by: str | None
    slo_target: str | None
    slo_attainment_objective: float | None
    slo_window_days: int | None


def build_snapshot(repo_root: Path) -> list[SnapshotRow]:
    """Resolve every published column against the register."""
    columns = scan_spark_jobs(repo_root / "spark")
    registry = load_registry(repo_root / "governance" / "cde_registry.yml")
    return [_row(column, registry) for column in columns]


def _row(column, registry: Registry) -> SnapshotRow:
    entry = registry.resolve(column.table, column.column)
    slo = registry.slos.get(entry.slo) if entry and entry.slo else None
    return SnapshotRow(
        table_name=column.table,
        column_name=column.column,
        layer=column.layer,
        description=column.description,
        tier=entry.tier if entry else None,
        owner=entry.owner if entry else None,
        definition=entry.definition if entry else None,
        quality_rules=", ".join(entry.quality_rules) if entry else "",
        quality_rule_count=len(entry.quality_rules) if entry else 0,
        control_gap=entry.control_gap if entry else None,
        slo=entry.slo if entry else None,
        slo_objective=slo.objective if slo else None,
        slo_measured_by=slo.measured_by if slo else None,
        slo_target=slo.target if slo else None,
        slo_attainment_objective=slo.attainment_objective if slo else None,
        slo_window_days=slo.window_days if slo else None,
    )


def render(rows: list[SnapshotRow]) -> str:
    """JSON Lines — one object per line, which Spark reads without a multiline flag."""
    return "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows)


def write_snapshot(repo_root: Path, destination: Path | None = None) -> tuple[Path, int]:
    """Write the snapshot next to the other landable reference files."""
    rows = build_snapshot(repo_root)
    path = destination or (repo_root / LOCAL_SNAPSHOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(rows), encoding="utf-8")
    return path, len(rows)
