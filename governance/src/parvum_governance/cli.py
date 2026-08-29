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
from parvum_governance.publish import write_snapshot


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


def publish(argv: list[str] | None = None) -> int:
    """`parvum-publish-registry` — write the landable snapshot of the register.

    Refuses to publish a register the gate rejects. A snapshot of a broken
    register would put wrong ownership into the lakehouse and onto a screen,
    which is worse than publishing nothing.
    """
    parser = argparse.ArgumentParser(description=publish.__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--out", type=Path, default=None, help="destination file (default: data/reference/)"
    )
    args = parser.parse_args(argv)

    root = args.repo_root or find_repo_root()
    result = check_repo(root)
    if not result.passed:
        print(format_report(result))
        print("refusing to publish a register that does not reconcile", file=sys.stderr)
        return 1

    path, count = write_snapshot(root, args.out)
    print(f"wrote {count} column records to {path}")
    return 0


def evaluate(argv: list[str] | None = None) -> int:
    """Measure whether the governance metadata changes an AI's answers.

    Asks the same questions twice — once with column names alone, once with
    every description, definition and governed measure the estate publishes —
    executes both answers against the warehouse, and scores them against
    hand-written ground truth. Needs DATABRICKS_HOST and OPENROUTER_API_KEY.
    """
    from parvum_governance.evaluation import render, run_eval

    parser = argparse.ArgumentParser(description=evaluate.__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--provider", default="openrouter", choices=("openrouter", "anthropic"))
    parser.add_argument("--model", default=None, help="override the provider's default model")
    parser.add_argument("--out", type=Path, default=None, help="also write the report to this file")
    args = parser.parse_args(argv)

    from functools import partial

    from parvum_governance.evaluation import PROVIDERS

    ask = PROVIDERS[args.provider]
    if args.model:
        ask = partial(ask, model=args.model)
    result = run_eval(args.repo_root or find_repo_root(), ask=ask)
    report = render(result)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
