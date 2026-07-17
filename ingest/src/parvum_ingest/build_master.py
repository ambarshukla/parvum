"""CLI: build the securities master for every instrument in the universe.

Gathers the ISINs held across all cached 13F filings (the same identifiers
the feeds carry), resolves them through OpenFIGI, and writes the master —
Unknown bucket included — to a gitignored reference file the silver layer
will later consume. Occasional and reviewed, like `fetch-13f`; not part of
feed generation.
"""

import argparse
from pathlib import Path

from parvum_ingest.accounts import UNIVERSE
from parvum_ingest.edgar_store import filings_on_disk, holdings_in_effect
from parvum_ingest.model import is_cins, isin_from_cusip
from parvum_ingest.reference import domicile_of
from parvum_ingest.securities_master import build_master, write_master

DEFAULT_CACHE = Path("../data/edgar")
DEFAULT_OUT = Path("../data/reference/securities_master.json")


def universe_isins(cache_dir: Path) -> list[str]:
    """Every ISIN held across all cached filings of the universe's filers.

    CINS holdings are excluded upstream (no ISIN is derivable); the rest are
    derived with their curated domicile, exactly as the books build them, so
    the master's keys match the ISINs bronze actually carries.
    """
    isins: set[str] = set()
    for cik in {spec.cik for spec in UNIVERSE}:
        for filing in filings_on_disk(cache_dir, cik):
            _, holdings = holdings_in_effect(cache_dir, cik, filing.filing_date)
            for h in holdings:
                if not is_cins(h.cusip):
                    isins.add(isin_from_cusip(h.cusip, country=domicile_of(h.cusip)).value)
    return sorted(isins)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the securities master via OpenFIGI.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="13F filing store")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="master file to write")
    args = parser.parse_args()

    isins = universe_isins(args.cache)
    if not isins:
        raise SystemExit(f"no ISINs found under {args.cache} — run `make fetch-13f` first")

    entries = build_master(isins)
    summary = write_master(entries, args.out)
    print(
        f"{summary['total']} securities -> {summary['mapped']} mapped, "
        f"{summary['unknown']} unknown -> {args.out}"
    )


if __name__ == "__main__":
    main()
