"""CLI: manufacture the raw feed pile a custodian would have sent us.

For each business day in the range, emits one delivery into
`<out>/date=YYYY-MM-DD/` covering the whole account universe:

- `<account>.semt002.xml`   (holdings, ISO 20022 — one file per account)
- `<account>.mt535.txt`     (holdings, SWIFT MT — one file per account)
- `CUSTGB2L.camt053.xml`    (cash — ONE file, a Stmt block per account)

The asymmetry is the formats' own: semt.002 and MT535 are per-safekeeping-
account messages, while camt.053 is built to carry many statements in one
file — so the custodian sends holdings per account and cash as a single
consolidated file, as real senders do.

Hive-style `date=` directories so Spark can partition-prune later.

Corruption policy (D-011): every holdings rendition is corrupted
*independently* — per account AND per format — so the semt.002 and MT535
views of the same account genuinely disagree sometimes, which is what
cross-feed reconciliation exists to catch. Cash statements are corrupted
per account before the file is assembled. Everything derives
deterministically from (date, account), so any historical day regenerates
byte-identically.

Ground truth (what was injected, per file, with checksums) is written to
`<out>/../manifests/YYYY-MM-DD.json` — deliberately OUTSIDE the raw
landing directory: the pipeline must never read it; only Phase 3's
detection-quality evaluation may.
"""

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from random import Random

from parvum_ingest.accounts import CUSTODIAN_BIC, UNIVERSE
from parvum_ingest.book import build_book, build_cash_statement
from parvum_ingest.defects import DefectConfig, DefectType, inject_cash, inject_holdings
from parvum_ingest.formats.camt053 import render_camt053
from parvum_ingest.formats.mt535 import render_mt535
from parvum_ingest.formats.semt002 import render_semt002

_HOLDINGS_POOL = (
    DefectType.MISSING_COST_BASIS,
    DefectType.MISTYPED_ISIN,
    DefectType.STALE_PRICE,
)
_CASH_POOL = (
    DefectType.DUPLICATE_TRANSACTION,
    DefectType.DROPPED_TRANSACTION,
    DefectType.SETTLEMENT_SHIFT,
)
# Per day and defect type, the chance it's present in that day's delivery.
_DEFECT_PROBABILITY = 0.25


def _day_seed(day: date, account_index: int, stream: int) -> int:
    # Derived from the calendar date so a given day is always regenerable;
    # salted per (account, stream) so every rendition corrupts independently —
    # across accounts as well as across formats.
    return int(day.strftime("%Y%m%d")) * 100 + account_index * 10 + stream


def _pick_defects(pool: tuple[DefectType, ...], rng: Random) -> tuple[DefectType, ...]:
    return tuple(d for d in pool if rng.random() < _DEFECT_PROBABILITY)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_day(day: date, out_dir: Path, edgar_cache: Path | None = None) -> dict:
    """Write one day's delivery for the whole universe; return its manifest entry."""
    day_dir = out_dir / f"date={day.isoformat()}"
    day_dir.mkdir(parents=True, exist_ok=True)

    streams = []

    def _emit(filename: str, fmt: str, account: str | None, text: str, injections: list) -> None:
        (day_dir / filename).write_text(text, encoding="utf-8", newline="\n")
        streams.append(
            {
                "name": filename,
                "format": fmt,
                "account": account,
                "bytes": len(text.encode("utf-8")),
                "sha256": _sha256(text),
                "injections": [r.model_dump(mode="json") for r in injections],
            }
        )

    cash_statements: list = []
    cash_injections: list = []
    for index, spec in enumerate(UNIVERSE):
        book = build_book(day, spec, edgar_cache)

        seed = _day_seed(day, index, 1)
        semt_cfg = DefectConfig(seed=seed, defects=_pick_defects(_HOLDINGS_POOL, Random(seed)))
        semt_book, semt_inj = inject_holdings(book, semt_cfg)
        _emit(
            f"{spec.account_id}.semt002.xml",
            "semt.002",
            spec.account_id,
            render_semt002(semt_book),
            semt_inj,
        )

        seed = _day_seed(day, index, 2)
        mt_cfg = DefectConfig(seed=seed, defects=_pick_defects(_HOLDINGS_POOL, Random(seed)))
        mt_book, mt_inj = inject_holdings(book, mt_cfg)
        _emit(
            f"{spec.account_id}.mt535.txt",
            "MT535",
            spec.account_id,
            render_mt535(mt_book),
            mt_inj,
        )

        seed = _day_seed(day, index, 3)
        cash_cfg = DefectConfig(seed=seed, defects=_pick_defects(_CASH_POOL, Random(seed)))
        cash_stmt, cash_inj = inject_cash(build_cash_statement(day, spec, edgar_cache), cash_cfg)
        cash_statements.append(cash_stmt)
        cash_injections.extend(cash_inj)

    # Cash is one consolidated file: each account's statement was corrupted
    # independently above, then the custodian bundles them.
    _emit(
        f"{CUSTODIAN_BIC[:8]}.camt053.xml",
        "camt.053",
        None,
        render_camt053(tuple(cash_statements)),
        cash_injections,
    )

    return {"date": day.isoformat(), "accounts": [s.account_id for s in UNIVERSE], "files": streams}


def generate(end: date, days: int, out_dir: Path, edgar_cache: Path | None = None) -> list[dict]:
    """Generate deliveries for the `days` calendar days ending at `end`,
    skipping weekends (custodians send on business days). Returns the
    manifests, which are also written to <out>/../manifests/."""
    manifest_dir = out_dir.parent / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifests = []
    for offset in range(days - 1, -1, -1):
        day = end - timedelta(days=offset)
        if day.weekday() >= 5:  # 5=Sat, 6=Sun
            continue
        manifest = generate_day(day, out_dir, edgar_cache)
        (manifest_dir / f"{day.isoformat()}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
        )
        manifests.append(manifest)
    return manifests


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic custodial feed files.")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today(), help="last day")
    parser.add_argument("--days", type=int, default=90, help="calendar days back from --end")
    parser.add_argument("--out", type=Path, default=Path("../data/raw"), help="landing directory")
    parser.add_argument(
        "--edgar-cache",
        type=Path,
        default=Path("../data/edgar"),
        help="13F filing store (populate with `make fetch-13f`)",
    )
    args = parser.parse_args()

    manifests = generate(args.end, args.days, args.out, args.edgar_cache)
    total_files = sum(len(m["files"]) for m in manifests)
    print(f"{len(manifests)} business days -> {total_files} files under {args.out}")


if __name__ == "__main__":
    main()
