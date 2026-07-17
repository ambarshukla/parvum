"""The securities master: feed identifiers → a conformed instrument record.

Silver's other half. The ownership graph says *whose* a position is; the
securities master says *what* the instrument is — mapping the ISINs feeds
carry onto FIGIs plus name, type, and sector, so positions across accounts
and formats can be joined, grouped, and reported on a single canonical key.

The universe's ISINs come from the 13F books (every security across every
cached filing); OpenFIGI resolves them. The output is a table keyed by ISIN
with the FIGI metadata, **plus an explicit record for every identifier
OpenFIGI could not map** — the "Unknown" bucket (D-022). Unmapped is a
first-class state, not a dropped row: a security the master can't identify
still shows up in a client's account and must be visible, flagged, and
routable to whoever curates reference data, exactly as the target product
surfaces an "Unknown" asset class rather than hiding it.
"""

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from parvum_reference.openfigi import FigiRecord, map_isins


class SecurityMasterEntry(BaseModel):
    """One instrument as the master knows it. `mapped` is False for the Unknown bucket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    isin: str
    mapped: bool
    figi: str | None = None
    name: str | None = None
    security_type: str | None = None
    market_sector: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None


def build_entries(mappings: dict[str, FigiRecord | None]) -> tuple[SecurityMasterEntry, ...]:
    """Turn raw ISIN → FIGI mappings into master entries, Unknowns included.

    Pure and offline: the network already happened in `map_isins`. Every input
    ISIN yields exactly one entry — a match becomes a mapped record, a miss
    becomes an unmapped one — so nothing silently disappears.
    """
    entries = []
    for isin in sorted(mappings):
        rec = mappings[isin]
        if rec is None:
            entries.append(SecurityMasterEntry(isin=isin, mapped=False))
        else:
            entries.append(
                SecurityMasterEntry(
                    isin=isin,
                    mapped=True,
                    figi=rec.figi,
                    name=rec.name,
                    security_type=rec.security_type,
                    market_sector=rec.market_sector,
                    ticker=rec.ticker,
                    exchange_code=rec.exchange_code,
                )
            )
    return tuple(entries)


def build_master(isins: list[str]) -> tuple[SecurityMasterEntry, ...]:
    """Fetch and assemble the master for a set of ISINs (network)."""
    return build_entries(map_isins(isins))


def write_master(entries: tuple[SecurityMasterEntry, ...], out: Path) -> dict:
    """Write the master to JSON with a small provenance header. Returns a summary."""
    mapped = [e for e in entries if e.mapped]
    unknown = [e for e in entries if not e.mapped]
    document = {
        "source": {
            "provider": "OpenFIGI v3 mapping API",
            "built": date.today().isoformat(),
            "total": len(entries),
            "mapped": len(mapped),
            "unknown": len(unknown),
        },
        "securities": [e.model_dump() for e in entries],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return document["source"]


def load_master(path: Path) -> tuple[SecurityMasterEntry, ...]:
    """Read a written master back into typed entries."""
    document = json.loads(path.read_text(encoding="utf-8"))
    return tuple(SecurityMasterEntry.model_validate(s) for s in document["securities"])
