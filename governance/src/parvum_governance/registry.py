"""Load and shape-check the Critical Data Element register.

The register (`governance/cde_registry.yml`) is the declared side of the
governance contract: for every column this platform publishes, who owns it,
how critical it is, and — where it is critical — what it means in business
terms, which control tests it, and what service level it is held to.

Two deliberate constraints:

* **The obligations live in code, not in the register.** `TIER_OBLIGATIONS`
  below decides what each tier owes. Putting that matrix in the YAML would
  let the same pull request that adds an unclassified column also relax the
  rule that catches it, which is not a control at all.
* **Every published column must be listed**, even when it needs nothing but
  a name. That listing is what makes a *new* column fail the gate: defaults
  fill in the boring fields, but they cannot fill in a key that isn't there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VERSION = 1

#: What each tier obliges its publisher to supply.
#:
#: `critical` also has to say something about control coverage — either the
#: quality rules that test it, or a named `control_gap` admitting there is
#: none yet. Silence is the one thing it cannot do.
TIER_OBLIGATIONS: dict[str, tuple[str, ...]] = {
    "critical": ("owner", "definition", "slo", "control_coverage"),
    "supporting": ("owner",),
    "operational": ("owner",),
}

TIERS = tuple(TIER_OBLIGATIONS)


class RegistryError(ValueError):
    """The register is malformed — a problem with the file, not with coverage."""


@dataclass(frozen=True)
class Slo:
    """A named service level that critical elements can be held to.

    `target` is the human sentence; `attainment_objective` and `window_days`
    are the machine-readable form of the same promise, and they are what makes
    attainment computable. An SLO stated only in prose can be quoted but never
    missed, which is the failure mode this pair exists to remove: the share of
    days in the trailing window on which `measured_by` must have passed.
    """

    name: str
    objective: str
    measured_by: str
    target: str
    attainment_objective: float
    window_days: int

    @property
    def error_budget_fraction(self) -> float:
        """The share of the window the SLO is allowed to miss before it is breached."""
        return 1.0 - self.attainment_objective


@dataclass(frozen=True)
class ColumnEntry:
    """The register's fully-resolved statement about one column."""

    table: str
    column: str
    tier: str | None = None
    owner: str | None = None
    definition: str | None = None
    quality_rules: tuple[str, ...] = ()
    control_gap: str | None = None
    slo: str | None = None

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}"

    @property
    def has_control_coverage(self) -> bool:
        """True when this entry either cites a control or names its absence."""
        return bool(self.quality_rules) or bool(self.control_gap)


@dataclass(frozen=True)
class TableEntry:
    """A registered table: its owner, its fallback tier, and its columns."""

    name: str
    owner: str | None
    default_tier: str | None
    columns: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Registry:
    """The whole register, loaded and shape-checked but not yet reconciled."""

    owners: dict[str, str]
    slos: dict[str, Slo]
    common_columns: dict[str, dict[str, Any]]
    tables: dict[str, TableEntry]

    def resolve(self, table: str, column: str) -> ColumnEntry | None:
        """The register's statement about one column, or None if unregistered.

        Three layers, most specific last: the table's defaults, then any
        `common_columns` entry for a column name that means the same thing
        everywhere (`rebuilt_at`, `client_id`), then the column's own entry.
        """
        registered = self.tables.get(table)
        if registered is None or column not in registered.columns:
            return None

        merged: dict[str, Any] = {}
        if registered.owner is not None:
            merged["owner"] = registered.owner
        if registered.default_tier is not None:
            merged["tier"] = registered.default_tier
        merged.update(self.common_columns.get(column, {}))
        merged.update(registered.columns[column] or {})

        rules = merged.get("quality_rules") or ()
        return ColumnEntry(
            table=table,
            column=column,
            tier=merged.get("tier"),
            owner=merged.get("owner"),
            definition=merged.get("definition"),
            quality_rules=tuple(rules),
            control_gap=merged.get("control_gap"),
            slo=merged.get("slo"),
        )

    def registered_keys(self) -> list[str]:
        """Every `table.column` the register claims, in file order."""
        return [
            f"{table.name}.{column}" for table in self.tables.values() for column in table.columns
        ]


_ENTRY_FIELDS = {"tier", "owner", "definition", "quality_rules", "control_gap", "slo"}


def _check_entry_shape(entry: Any, *, where: str) -> dict[str, Any]:
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise RegistryError(
            f"{where}: expected a mapping or an empty value, got {type(entry).__name__}"
        )
    unknown = sorted(set(entry) - _ENTRY_FIELDS)
    if unknown:
        raise RegistryError(
            f"{where}: unknown field(s) {unknown}; allowed are {sorted(_ENTRY_FIELDS)}"
        )
    rules = entry.get("quality_rules")
    if rules is not None and not isinstance(rules, list):
        raise RegistryError(f"{where}: quality_rules must be a list, got {type(rules).__name__}")
    return entry


def load_registry(path: Path) -> Registry:
    """Read the register and check its shape (not its coverage — that is the gate's job)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RegistryError(f"{path.name}: top level is not a mapping")

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise RegistryError(
            f"{path.name}: unsupported register version {version!r} (expected {SUPPORTED_VERSION})"
        )

    owners = raw.get("owners") or {}
    if not isinstance(owners, dict) or not owners:
        raise RegistryError(
            f"{path.name}: `owners` must be a non-empty mapping of "
            f"role -> what it is accountable for"
        )

    slos: dict[str, Slo] = {}
    for name, body in (raw.get("slos") or {}).items():
        if not isinstance(body, dict):
            raise RegistryError(f"{path.name}: slo {name!r} is not a mapping")
        missing = sorted(
            {"objective", "measured_by", "target", "attainment_objective", "window_days"}
            - set(body)
        )
        if missing:
            raise RegistryError(f"{path.name}: slo {name!r} is missing {missing}")
        objective_raw = body["attainment_objective"]
        if not isinstance(objective_raw, (int, float)) or isinstance(objective_raw, bool):
            raise RegistryError(
                f"{path.name}: slo {name!r} attainment_objective must be a number between "
                f"0 and 1, not {objective_raw!r}"
            )
        if not 0 < float(objective_raw) <= 1:
            raise RegistryError(
                f"{path.name}: slo {name!r} attainment_objective must be in (0, 1]; "
                f"got {objective_raw!r}. It is the share of days the metric must pass — "
                f"a percentage expressed as a fraction."
            )
        window_raw = body["window_days"]
        if not isinstance(window_raw, int) or isinstance(window_raw, bool) or window_raw < 1:
            raise RegistryError(
                f"{path.name}: slo {name!r} window_days must be a positive integer, "
                f"not {window_raw!r}"
            )
        slos[name] = Slo(
            name=name,
            objective=body["objective"],
            measured_by=body["measured_by"],
            target=body["target"],
            attainment_objective=float(objective_raw),
            window_days=window_raw,
        )

    common_columns = {
        name: _check_entry_shape(entry, where=f"common_columns.{name}")
        for name, entry in (raw.get("common_columns") or {}).items()
    }

    tables: dict[str, TableEntry] = {}
    for name, body in (raw.get("tables") or {}).items():
        if not isinstance(body, dict):
            raise RegistryError(f"{path.name}: table {name!r} is not a mapping")
        columns_raw = body.get("columns")
        if not isinstance(columns_raw, dict):
            raise RegistryError(f"{path.name}: table {name!r} must have a `columns` mapping")
        tables[name] = TableEntry(
            name=name,
            owner=body.get("owner"),
            default_tier=body.get("default_tier"),
            columns={
                column: _check_entry_shape(entry, where=f"{name}.{column}")
                for column, entry in columns_raw.items()
            },
        )

    return Registry(owners=owners, slos=slos, common_columns=common_columns, tables=tables)
