"""`parvum-check-governance` — the publisher-obligation gate, as a command.

Exits non-zero on any finding, so CI fails the pull request that introduced
it. The report is written to be read by whoever broke the build: findings
grouped by rule, then the coverage summary the governance function reports
upward.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from parvum_governance.check import GateResult, check_repo, find_repo_root


def format_report(result: GateResult) -> str:
    lines: list[str] = []
    coverage = result.coverage

    if result.findings:
        by_rule: dict[str, list[str]] = defaultdict(list)
        for finding in result.findings:
            by_rule[finding.rule].append(f"    {finding.key}: {finding.message}")
        lines.append(f"{len(result.findings)} governance finding(s):")
        for rule in sorted(by_rule):
            lines.append(f"  {rule} ({len(by_rule[rule])})")
            lines.extend(by_rule[rule])
        lines.append("")

    lines.append("Coverage")
    lines.append(f"  columns published        {coverage.published}")
    lines.append(
        f"  classified in register   {coverage.registered} ({coverage.classified_pct:.1f}%)"
    )
    for tier, count in sorted(coverage.by_tier.items()):
        lines.append(f"    {tier:<12}           {count}")
    lines.append(
        f"  critical with a control  {coverage.critical_with_controls}"
        f"/{coverage.critical} ({coverage.control_coverage_pct:.1f}%)"
    )
    lines.append(f"  critical with a known gap {coverage.critical_with_gap}")
    lines.append("")
    lines.append("PASS" if result.passed else "FAIL")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="checkout to check (default: found by walking up from this file)",
    )
    args = parser.parse_args(argv)

    root = args.repo_root or find_repo_root()
    result = check_repo(root)
    print(format_report(result))
    return 0 if result.passed else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
