"""Securities master: mapping assembly, the Unknown bucket, and round-trip.

Offline. The OpenFIGI network call (`map_isins`) is exercised separately with
a stubbed transport; everything here works on already-fetched mappings, so
CI never depends on OpenFIGI being reachable.
"""

import json
from pathlib import Path

from parvum_ingest.openfigi import FigiRecord
from parvum_ingest.securities_master import (
    SecurityMasterEntry,
    build_entries,
    load_master,
    write_master,
)

# A tiny mapping standing in for an OpenFIGI response: two mapped, one miss.
_MAPPINGS: dict[str, FigiRecord | None] = {
    "US0378331005": FigiRecord(
        figi="BBG000B9XRY4",
        name="APPLE INC",
        security_type="Common Stock",
        market_sector="Equity",
        ticker="AAPL",
        exchange_code="US",
    ),
    "CA1363751027": FigiRecord(
        figi="BBG000GLP2C0",
        name="CANADIAN NATL RAILWAY CO",
        security_type="Common Stock",
        market_sector="Equity",
    ),
    "US9999999999": None,  # OpenFIGI had no match — the Unknown case
}


def test_every_isin_yields_exactly_one_entry() -> None:
    # Nothing is dropped: a miss becomes an entry too, or securities would
    # silently vanish from the master.
    entries = build_entries(_MAPPINGS)
    assert {e.isin for e in entries} == set(_MAPPINGS)


def test_mapped_entry_carries_the_figi_metadata() -> None:
    entries = build_entries(_MAPPINGS)
    apple = next(e for e in entries if e.isin == "US0378331005")
    assert apple.mapped
    assert apple.figi == "BBG000B9XRY4"
    assert apple.security_type == "Common Stock"
    assert apple.market_sector == "Equity"


def test_unmapped_isin_becomes_a_flagged_unknown() -> None:
    # The whole point: an unmappable identifier is a visible, flagged record,
    # not a hidden failure — it still shows up in a client's account.
    entries = build_entries(_MAPPINGS)
    unknown = next(e for e in entries if e.isin == "US9999999999")
    assert unknown.mapped is False
    assert unknown.figi is None
    assert unknown.name is None


def test_entries_are_ordered_by_isin() -> None:
    isins = [e.isin for e in build_entries(_MAPPINGS)]
    assert isins == sorted(isins)


def test_write_summary_counts_mapped_and_unknown(tmp_path: Path) -> None:
    summary = write_master(build_entries(_MAPPINGS), tmp_path / "m.json")
    assert summary["total"] == 3
    assert summary["mapped"] == 2
    assert summary["unknown"] == 1


def test_written_master_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "m.json"
    original = build_entries(_MAPPINGS)
    write_master(original, out)
    assert load_master(out) == original


def test_master_document_records_provenance(tmp_path: Path) -> None:
    out = tmp_path / "m.json"
    write_master(build_entries(_MAPPINGS), out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["source"]["provider"].startswith("OpenFIGI")
    assert "built" in doc["source"]


def test_entry_validates_shape() -> None:
    # Mapped/unknown are representable; the model is the contract silver reads.
    ok = SecurityMasterEntry(isin="US0378331005", mapped=True, figi="BBG000B9XRY4")
    assert ok.figi == "BBG000B9XRY4"
    unknown = SecurityMasterEntry(isin="US9999999999", mapped=False)
    assert unknown.figi is None
