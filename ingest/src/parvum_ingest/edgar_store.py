"""Local store of 13F filings, and point-in-time selection over them.

This replaces the committed seed extract (D-014's original mechanism). 13F
data is *pipeline input*, not source code: it lives outside git in a plain
directory of immutable filings — locally under `data/edgar/` (gitignored),
in CI fetched fresh per run — mirroring how the lakehouse treats raw files.

Layout, one directory per filing, closed over by its accession number:

    <cache>/cik=<cik>/accession=<accession-no-dashes>/
        filing.json             # Filing13F fields: who, filed when, period
        information_table.xml   # the raw holdings XML, as received

**Why determinism survives leaving git.** The old argument for committing
the seed was byte-identical regeneration (D-011). That property actually
rests on something better: EDGAR filings are immutable and each is pinned by
its accession number, so "the set of filings filed on or before date D" is a
fixed historical fact. Sync fetches a filing at most once (an existing
directory is never re-fetched); selection is pure over what's on disk.

**Point-in-time rule:** the filing in effect on `as_of` is the latest one
with `filing_date <= as_of` — *filed*, not period end. Holdings become
knowable when the filing lands (~45 days after quarter end), and a custodian
statement can only reflect what exists. This is the as-of vs filed-at
distinction (bitemporal data) in its simplest usable form.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path

from parvum_ingest.edgar import (
    EdgarError,
    Filing13F,
    Holding13F,
    _get,
    information_table_url,
    list_13f_filings,
    parse_information_table,
)


def _filing_dir(cache_dir: Path, filing: Filing13F) -> Path:
    return cache_dir / f"cik={filing.cik}" / f"accession={filing.accession.replace('-', '')}"


def sync(cache_dir: Path, cik: int, *, limit: int = 4) -> tuple[Filing13F, ...]:
    """Bring the local store up to date for one filer (network).

    Fetches the metadata list, then downloads only filings not already on
    disk — immutability makes "directory exists" a complete freshness check.
    Returns everything now cached for the filer, newest first.
    """
    for filing in list_13f_filings(cik, limit=limit):
        target = _filing_dir(cache_dir, filing)
        if target.is_dir():
            continue
        xml = _get(information_table_url(filing)).decode("utf-8")
        # Write into a temp dir and rename: the directory's existence is the
        # "already fetched" signal, so it must never exist half-written.
        partial = target.with_name(target.name + ".partial")
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "information_table.xml").write_text(xml, encoding="utf-8", newline="\n")
        (partial / "filing.json").write_text(
            filing.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        partial.rename(target)
    return filings_on_disk(cache_dir, cik)


def filings_on_disk(cache_dir: Path, cik: int) -> tuple[Filing13F, ...]:
    """Every cached filing for a filer, newest first. Offline."""
    root = cache_dir / f"cik={cik}"
    if not root.is_dir():
        return ()
    filings = [
        Filing13F.model_validate_json((entry / "filing.json").read_text(encoding="utf-8"))
        for entry in sorted(root.iterdir())
        if entry.is_dir() and not entry.name.endswith(".partial")
    ]
    return tuple(sorted(filings, key=lambda f: f.filing_date, reverse=True))


def filing_in_effect(cache_dir: Path, cik: int, as_of: date) -> Filing13F:
    """The filing a statement dated `as_of` would be built from."""
    cached = filings_on_disk(cache_dir, cik)
    if not cached:
        raise EdgarError(
            f"no 13F filings cached for CIK {cik} under {cache_dir} — "
            "run `make fetch-13f` to sync the store from EDGAR"
        )
    for filing in cached:  # newest first
        if filing.filing_date <= as_of:
            return filing
    raise EdgarError(
        f"no filing for CIK {cik} was public by {as_of} (earliest cached: filed "
        f"{cached[-1].filing_date}) — extend the sync limit, or don't generate that far back"
    )


@lru_cache(maxsize=32)
def _holdings_for(table_path: str) -> tuple[Holding13F, ...]:
    # Keyed by the XML file's resolved path: immutable content, so caching by
    # location is safe, and distinct cache dirs (real vs test fixtures) never
    # collide.
    return parse_information_table(Path(table_path).read_text(encoding="utf-8"))


def holdings_in_effect(
    cache_dir: Path, cik: int, as_of: date
) -> tuple[Filing13F, tuple[Holding13F, ...]]:
    """The filing in effect on `as_of`, with its parsed holdings. Offline."""
    filing = filing_in_effect(cache_dir, cik, as_of)
    table = _filing_dir(cache_dir, filing) / "information_table.xml"
    return filing, _holdings_for(str(table.resolve()))
