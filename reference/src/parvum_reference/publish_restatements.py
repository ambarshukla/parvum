"""CLI: write the declared book restatements out for landing.

Same pull-not-push contract as the FX rates, the securities master and the CDE
register (D-006): the repo is the source of truth, a resolved snapshot lands in
the volume, and the Spark side reads the snapshot under an explicit schema. A
restatement is a decision with a reviewable diff behind it, which is why it
lives in Python next to the divisors it describes rather than in a table
somebody could quietly UPDATE.

Refuses to publish while `accounts.py` carries a divisor the register does not
account for — publishing a register that already disagrees with the book would
put a stale explanation in front of a live number.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from parvum_reference.restatements import RESTATEMENTS, undeclared_divisor_changes

LOCAL_SNAPSHOT = Path("data/reference/book_restatements.json")


@dataclass(frozen=True)
class SnapshotRow:
    """One landed restatement record. Decimals go out as strings: JSON floats
    would quietly round a divisor, and the Spark side casts explicitly."""

    effective_date: str
    account_id: str
    divisor_before: str
    divisor_after: str
    reason: str
    decision_ref: str


def render() -> str:
    """JSON Lines — one object per line, which Spark reads without a multiline flag."""
    rows = [
        SnapshotRow(
            effective_date=entry.effective_date.isoformat(),
            account_id=entry.account_id,
            divisor_before=str(entry.divisor_before),
            divisor_after=str(entry.divisor_after),
            reason=entry.reason,
            decision_ref=entry.decision_ref,
        )
        for entry in sorted(RESTATEMENTS, key=lambda r: (r.effective_date, r.account_id))
    ]
    return "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows)


def write_snapshot(destination: Path) -> int:
    drift = undeclared_divisor_changes()
    if drift:
        detail = "; ".join(
            f"{account_id}: register says {declared}, accounts.py carries {live}"
            for account_id, (declared, live) in sorted(drift.items())
        )
        raise ValueError(
            "book restatement register disagrees with the live divisors — record the "
            f"change in restatements.py before publishing ({detail})"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(), encoding="utf-8")
    return len(RESTATEMENTS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the declared book restatements.")
    parser.add_argument(
        "--out",
        type=Path,
        default=LOCAL_SNAPSHOT,
        help=f"where to write the snapshot (default: {LOCAL_SNAPSHOT})",
    )
    args = parser.parse_args()

    count = write_snapshot(args.out)
    print(f"book restatements written: {count} records -> {args.out}")


if __name__ == "__main__":
    main()
