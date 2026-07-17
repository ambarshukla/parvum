"""CLI: sync the local 13F filing store from SEC EDGAR.

Replaces the committed seed extract (D-017): filings are pipeline input, so
they live in a gitignored data directory, fetched here and read point-in-time
by the book builder. Sync is incremental — filings are immutable, so anything
already on disk is never fetched again — and therefore cheap to run daily.
"""

import argparse
from pathlib import Path

from parvum_ingest.edgar_store import sync

# The filers whose books seed the generated accounts. One for now; the
# multi-account universe adds more.
FILERS: dict[int, str] = {
    1067983: "Berkshire Hathaway",
}

DEFAULT_CACHE = Path("../data/edgar")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the local 13F filing store from EDGAR.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="store directory")
    parser.add_argument(
        "--limit", type=int, default=4, help="filings to keep per filer (quarters of history)"
    )
    args = parser.parse_args()

    for cik, name in FILERS.items():
        filings = sync(args.cache, cik, limit=args.limit)
        newest = filings[0]
        print(
            f"{name} (CIK {cik}): {len(filings)} filings cached; newest {newest.accession} "
            f"(period {newest.period}, filed {newest.filing_date})"
        )


if __name__ == "__main__":
    main()
