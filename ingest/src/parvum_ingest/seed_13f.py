"""Build the committed seed extract from a real 13F filing.

The extract is **checked into the repo** rather than fetched when feeds are
generated, and that is the whole point: the generator must produce
byte-identical files for a given date (D-011), which is impossible if its
inputs depend on a network call that can change or fail. Fetching is an
occasional, reviewed act; generating is deterministic.

Identifier policy — the interesting part:

- **US-domestic CUSIPs get a derived ISIN.** The ISO 6166 construction rule
  is real, so this is arithmetic rather than invention (see `isin_from_cusip`).
- **CINS codes are excluded, and counted.** Chubb's `H1467J104` would become
  `USH1467J104…`, an identifier that exists nowhere; its real ISIN is
  `CH0044328745`, knowable only by lookup. Fabricating it would poison the
  securities master we haven't built yet (D-004). Recording the exclusion is
  the honest move, and Phase 2's OpenFIGI mapping is what brings these names
  back.

No retrieval timestamp is recorded, deliberately. The accession number
already pins the exact, immutable filing, and git records when we committed
it. A timestamp would make the file differ on every fetch — which would turn
the scheduled check into a generator of meaningless pull requests.
"""

import argparse
import json
from pathlib import Path

from parvum_ingest.edgar import Filing13F, Holding13F, fetch_13f_holdings
from parvum_ingest.model import isin_from_cusip

# Berkshire Hathaway. A deliberately boring choice: ~30 large, liquid,
# recognisable US names, which is a plausible private-client book once scaled
# down — as opposed to a quant filer's several thousand micro-positions.
BERKSHIRE_CIK = 1067983

DEFAULT_SEED_PATH = Path("seed/holdings_13f.json")


def build_seed(filing: Filing13F, holdings: tuple[Holding13F, ...]) -> dict:
    """Turn a parsed filing into the seed document, applying identifier policy."""
    included: list[dict] = []
    excluded: list[dict] = []

    for holding in holdings:
        try:
            isin = isin_from_cusip(holding.cusip)
        except ValueError as exc:
            excluded.append({"cusip": holding.cusip, "issuer": holding.issuer, "reason": str(exc)})
            continue
        included.append(
            {
                "cusip": holding.cusip,
                "isin": isin.value,
                "issuer": holding.issuer,
                "title_of_class": holding.title_of_class,
                # Quantities and money as strings: JSON numbers are IEEE
                # doubles, and a share count of 227,917,808 or a value of
                # $57,843,260,493 must survive the round trip exactly.
                "shares": str(holding.shares),
                "value_usd": str(holding.value_usd),
            }
        )

    return {
        "source": {
            "filer": filing.filer,
            "cik": filing.cik,
            "form": "13F-HR",
            "accession": filing.accession,
            "period": filing.period.isoformat(),
            "filing_date": filing.filing_date.isoformat(),
            "licence": "public domain (US government work)",
        },
        "holdings": included,
        "excluded": excluded,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a filer's latest 13F-HR and write the committed seed extract."
    )
    parser.add_argument("--cik", type=int, default=BERKSHIRE_CIK, help="filer's SEC CIK")
    parser.add_argument("--out", type=Path, default=DEFAULT_SEED_PATH, help="seed file to write")
    args = parser.parse_args()

    filing, holdings = fetch_13f_holdings(args.cik)
    seed = build_seed(filing, holdings)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(
        f"{filing.filer} {filing.accession} (period {filing.period}) -> "
        f"{len(seed['holdings'])} holdings, {len(seed['excluded'])} excluded -> {args.out}"
    )


if __name__ == "__main__":
    main()
