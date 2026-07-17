"""The generator CLI: business-day cadence, determinism, parseable output,
and ground truth kept out-of-band."""

import json
from datetime import date
from pathlib import Path

from parvum_ingest.accounts import UNIVERSE
from parvum_ingest.formats.camt053 import parse_camt053
from parvum_ingest.formats.mt535 import parse_mt535
from parvum_ingest.formats.semt002 import parse_semt002
from parvum_ingest.generate import generate

# Fri 2026-07-10 .. Mon 2026-07-13: four calendar days, two business days.
END = date(2026, 7, 13)


def test_weekends_are_skipped(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    manifests = generate(END, days=4, out_dir=raw)
    assert [m["date"] for m in manifests] == ["2026-07-10", "2026-07-13"]
    assert sorted(p.name for p in raw.iterdir()) == ["date=2026-07-10", "date=2026-07-13"]


def test_each_day_delivers_the_whole_universe(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    generate(END, days=1, out_dir=raw)
    day_dir = raw / "date=2026-07-13"

    # Two holdings files per account, plus ONE consolidated cash file.
    assert len(list(day_dir.iterdir())) == 2 * len(UNIVERSE) + 1

    for spec in UNIVERSE:
        semt = parse_semt002((day_dir / f"{spec.account_id}.semt002.xml").read_text("utf-8"))
        mt = parse_mt535((day_dir / f"{spec.account_id}.mt535.txt").read_text("utf-8"))
        assert semt.as_of == mt.as_of == END
        assert semt.account.account_id == mt.account.account_id == spec.account_id

    cash = parse_camt053((day_dir / "CUSTGB2L.camt053.xml").read_text("utf-8"))
    assert [s.account.account_id for s in cash] == [spec.account_id for spec in UNIVERSE]
    assert all(s.as_of == END for s in cash)


def test_accounts_hold_genuinely_different_books(tmp_path: Path) -> None:
    # Different filers seed different accounts: the universe must not be five
    # renditions of one portfolio.
    raw = tmp_path / "raw"
    generate(END, days=1, out_dir=raw)
    day_dir = raw / "date=2026-07-13"

    names_by_account = {
        spec.account_id: {
            p.security_name
            for p in parse_semt002(
                (day_dir / f"{spec.account_id}.semt002.xml").read_text("utf-8")
            ).positions
        }
        for spec in UNIVERSE
    }
    assert names_by_account["60011234"] != names_by_account["FQ5521"]
    assert names_by_account["FQ5521"] != names_by_account["X4478210"]
    # Same filer, different accounts -> same names (scale differs, not content).
    assert names_by_account["60011234"] == names_by_account["60018852"]


def test_the_eur_account_reports_cash_in_eur(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    generate(END, days=1, out_dir=raw)
    cash = parse_camt053((raw / "date=2026-07-13" / "CUSTGB2L.camt053.xml").read_text("utf-8"))
    currencies = {s.account.account_id: s.balances[0].balance.currency for s in cash}
    assert currencies["FQ5521"] == "EUR"
    assert currencies["60011234"] == "USD"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    generate(END, days=7, out_dir=a)
    generate(END, days=7, out_dir=b)
    files_a = sorted(p.relative_to(a) for p in a.rglob("*.*"))
    files_b = sorted(p.relative_to(b) for p in b.rglob("*.*"))
    assert files_a == files_b
    for rel in files_a:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_ground_truth_lives_outside_the_landing_dir(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    generate(END, days=1, out_dir=raw)
    manifest_path = tmp_path / "manifests" / "2026-07-13.json"
    assert manifest_path.exists()
    # Nothing under raw/ mentions injections — the pipeline can't cheat.
    assert not list(raw.rglob("*.json"))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {f["format"] for f in manifest["files"]} == {"semt.002", "MT535", "camt.053"}
    assert all(f["sha256"] and f["bytes"] > 0 for f in manifest["files"])


def test_holdings_streams_are_corrupted_independently(tmp_path: Path) -> None:
    # Across a spread of days, the semt.002 and MT535 injections must not
    # always coincide — independent corruption is what makes cross-format
    # reconciliation meaningful (D-011).
    manifests = generate(date(2026, 7, 13), days=60, out_dir=tmp_path / "raw")
    differing = 0
    for m in manifests:
        by_format = {f["format"]: f["injections"] for f in m["files"]}
        if by_format["semt.002"] != by_format["MT535"]:
            differing += 1
    assert differing > 0
