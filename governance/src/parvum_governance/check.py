"""The gate: reconcile the register against what the platform actually publishes.

Six rules, each of which fails the build. Together they are the mechanical
form of a publisher's responsibilities — the point being that nobody has to
remember them, and nobody can quietly skip them:

`unclassified`
    A column reaches the catalog with no entry in the register. Adding a
    column is allowed; declining to say who owns it and how critical it is
    is not. This is the rule that makes the register keep up with the code.

`orphan`
    The register describes a column the platform no longer publishes. Stops
    the register rotting into a museum of renamed and dropped fields.

`missing_description`
    A published column carries no catalog description. Schema without meaning
    is not consumable — by an analyst or by a model.

`incomplete_obligation`
    A tier's obligations are unmet: a critical element with no owner, no
    business definition, no service level, or silence about whether any
    control tests it.

`invalid_reference`
    The register points at something that does not exist — an unknown owner
    role, an unknown tier, an SLO it never defined, or a quality rule that
    the DQ layer does not actually compute. A control you cannot execute is
    worse than an admitted gap, because it reads as covered.

`unheld_slo`
    A service level is declared but no critical element is held to it. The
    mirror of `orphan`, pointed at the SLO block: a promise nobody is on the
    hook for is decoration, and — since attainment is computed from the SLOs
    the register's own elements cite — it would also never be measured. Delete
    it, or hold something to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from parvum_governance.registry import TIER_OBLIGATIONS, TIERS, Registry, load_registry
from parvum_governance.schema_scan import PublishedColumn, scan_dq_metric_names, scan_spark_jobs


@dataclass(frozen=True)
class Finding:
    """One way in which the register and the platform disagree."""

    rule: str
    key: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.key}: {self.message}"


@dataclass(frozen=True)
class Coverage:
    """What the register says about the estate, once reconciled."""

    published: int
    registered: int
    by_tier: dict[str, int]
    critical_with_controls: int
    critical_with_gap: int

    @property
    def classified_pct(self) -> float:
        if not self.published:
            return 100.0
        return 100.0 * self.registered / self.published

    @property
    def critical(self) -> int:
        return self.by_tier.get("critical", 0)

    @property
    def control_coverage_pct(self) -> float:
        """Share of critical elements with a real control, not an admitted gap."""
        if not self.critical:
            return 100.0
        return 100.0 * self.critical_with_controls / self.critical


@dataclass(frozen=True)
class GateResult:
    findings: list[Finding]
    coverage: Coverage

    @property
    def passed(self) -> bool:
        return not self.findings


def check(
    columns: list[PublishedColumn],
    registry: Registry,
    dq_metric_names: set[str],
) -> GateResult:
    """Run every rule and summarise coverage."""
    findings: list[Finding] = []
    published_keys = {column.key for column in columns}
    by_tier: dict[str, int] = {}
    critical_with_controls = 0
    critical_with_gap = 0
    registered = 0
    slos_held: set[str] = set()

    for column in columns:
        if not column.description.strip():
            findings.append(
                Finding(
                    "missing_description",
                    column.key,
                    f"published by {column.source_file} with an empty catalog comment",
                )
            )

        entry = registry.resolve(column.table, column.column)
        if entry is None:
            findings.append(
                Finding(
                    "unclassified",
                    column.key,
                    f"published by {column.source_file} but absent from the register — "
                    f"add it under tables.{column.table}.columns",
                )
            )
            continue

        registered += 1
        findings.extend(_check_references(entry, registry, dq_metric_names))

        if entry.tier not in TIERS:
            # Already reported as an invalid reference; obligations for an
            # unknown tier are unknowable, so stop here rather than guess.
            continue

        by_tier[entry.tier] = by_tier.get(entry.tier, 0) + 1
        findings.extend(_check_obligations(entry))
        if entry.tier == "critical":
            if entry.slo:
                slos_held.add(entry.slo)
            if entry.quality_rules:
                critical_with_controls += 1
            elif entry.control_gap:
                critical_with_gap += 1

    for key in registry.registered_keys():
        if key not in published_keys:
            findings.append(
                Finding(
                    "orphan",
                    key,
                    "in the register but no Spark job publishes it — "
                    "remove the entry, or restore the column",
                )
            )

    for name in sorted(set(registry.slos) - slos_held):
        findings.append(
            Finding(
                "unheld_slo",
                name,
                "declared under `slos` but no critical element is held to it — "
                "cite it from the elements it governs, or remove it. Attainment is "
                "computed only for SLOs something is held to, so an unheld one is "
                "never measured either",
            )
        )

    coverage = Coverage(
        published=len(columns),
        registered=registered,
        by_tier=by_tier,
        critical_with_controls=critical_with_controls,
        critical_with_gap=critical_with_gap,
    )
    return GateResult(findings=sorted(findings, key=lambda f: (f.rule, f.key)), coverage=coverage)


def _check_references(entry, registry: Registry, dq_metric_names: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    if entry.tier is not None and entry.tier not in TIERS:
        findings.append(
            Finding(
                "invalid_reference",
                entry.key,
                f"unknown tier {entry.tier!r}; expected one of {list(TIERS)}",
            )
        )
    if entry.owner is not None and entry.owner not in registry.owners:
        findings.append(
            Finding(
                "invalid_reference",
                entry.key,
                f"unknown owner {entry.owner!r}; add the role under `owners`",
            )
        )
    if entry.slo is not None and entry.slo not in registry.slos:
        findings.append(
            Finding(
                "invalid_reference", entry.key, f"unknown slo {entry.slo!r}; define it under `slos`"
            )
        )
    for rule in entry.quality_rules:
        if rule not in dq_metric_names:
            findings.append(
                Finding(
                    "invalid_reference",
                    entry.key,
                    f"quality rule {rule!r} is not a metric the DQ layer computes "
                    f"— cite one of {sorted(dq_metric_names)}, or record a control_gap",
                )
            )
    return findings


def _check_obligations(entry) -> list[Finding]:
    findings: list[Finding] = []
    for obligation in TIER_OBLIGATIONS[entry.tier]:
        if obligation == "control_coverage":
            if not entry.has_control_coverage:
                findings.append(
                    Finding(
                        "incomplete_obligation",
                        entry.key,
                        "tier 'critical' must either cite quality_rules or state a "
                        "control_gap saying what is missing and what would close it",
                    )
                )
            continue
        if not getattr(entry, obligation):
            findings.append(
                Finding(
                    "incomplete_obligation",
                    entry.key,
                    f"tier {entry.tier!r} requires {obligation!r}",
                )
            )
    return findings


def check_repo(repo_root: Path) -> GateResult:
    """Run the gate against a checkout, wiring the scans to their real paths."""
    spark_dir = repo_root / "spark"
    registry_path = repo_root / "governance" / "cde_registry.yml"
    return check(
        columns=scan_spark_jobs(spark_dir),
        registry=load_registry(registry_path),
        dq_metric_names=scan_dq_metric_names(
            spark_dir / "dq_recon.py", spark_dir / "gold_reports.py"
        ),
    )


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up to the checkout root, identified by the workspace's own markers."""
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ruff.toml").is_file() and (candidate / "spark").is_dir():
            return candidate
    raise FileNotFoundError(f"no repository root (ruff.toml + spark/) above {current}")
