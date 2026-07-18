"""CLI: fetch ECB reference rates into the local store.

Lives in the reference package (unlike parvum-fetch-13f and
parvum-build-master, which live in ingest) because it touches nothing of
ingest's: no accounts, no 13F store — just the ECB and a JSON file. The
CLI belongs to the package whose data it maintains.
"""

import argparse
from pathlib import Path

from parvum_reference.ecb import fetch_rates, write_rates


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ECB EUR/USD reference rates.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/reference/fx_rates.json"),
        help="where to write the rates store (default: data/reference/fx_rates.json)",
    )
    args = parser.parse_args()

    summary = write_rates(fetch_rates(), args.out)
    print(
        f"fx rates written: {summary['days']} days "
        f"({summary['first']} -> {summary['last']}), "
        f"{summary['base']}/{summary['quote']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
