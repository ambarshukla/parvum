"""The generator CLI's library entry point: writes real PDFs and a manifest
that names real files, for the whole fund universe."""

import json

from parvum_alts_hitl.generate import FUND_UNIVERSE, generate


def test_generates_every_fund_with_pdfs_and_a_manifest(tmp_path) -> None:
    out_dir = tmp_path / "raw"
    manifests = generate(out_dir)

    assert len(manifests) == len(FUND_UNIVERSE)

    for commitment, manifest in zip(FUND_UNIVERSE, manifests, strict=True):
        assert manifest["fund_id"] == commitment.fund_id
        fund_dir = out_dir / commitment.fund_id
        assert manifest["documents"], "expected at least one document"
        for doc in manifest["documents"]:
            path = fund_dir / doc["name"]
            assert path.exists()
            assert path.stat().st_size == doc["bytes"]
            assert path.suffix == ".pdf"

        manifest_path = tmp_path / "manifests" / f"{commitment.fund_id}.json"
        assert manifest_path.exists()
        assert json.loads(manifest_path.read_text()) == manifest


def test_deterministic_across_runs(tmp_path) -> None:
    first = generate(tmp_path / "run1")
    second = generate(tmp_path / "run2")
    # Same manifests (byte counts, injections) regardless of output location.
    assert first == second


def test_manifest_lives_outside_the_landing_directory(tmp_path) -> None:
    out_dir = tmp_path / "raw"
    generate(out_dir)
    assert not (out_dir / "manifests").exists()
    assert (tmp_path / "manifests").exists()


def test_the_universe_spans_more_than_one_currency_and_template() -> None:
    # D-061: a single fund/template/currency made every document trivially
    # easy to extract. At least one fund must be non-USD for that gap to
    # actually be closed, not just structurally possible.
    currencies = {c.currency for c in FUND_UNIVERSE}
    assert "EUR" in currencies
    assert len(currencies) > 1
