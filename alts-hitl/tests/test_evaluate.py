"""Eval scoring, tested against fixture manifest/extracted-JSON files —
no LLM call involved, this only exercises the comparison logic."""

import json

from parvum_alts_hitl.evaluate import compare_document, run_eval


def test_compare_document_exact_match_ignores_fund_id() -> None:
    truth = {"fund_id": "F1", "call_amount": "150000.00", "purpose": "x"}
    extracted = {"call_amount": "150000.00", "purpose": "x"}

    result = compare_document(truth, extracted)

    assert result["exact_match"] is True
    assert result["mismatches"] == []
    assert result["field_count"] == 2


def test_compare_document_reports_a_mismatch() -> None:
    truth = {"call_amount": "150000.00"}
    extracted = {"call_amount": "510000.00"}

    result = compare_document(truth, extracted)

    assert result["exact_match"] is False
    assert result["mismatches"] == [
        {"field": "call_amount", "expected": "150000.00", "extracted": "510000.00"}
    ]


def test_compare_document_treats_equivalent_decimals_as_matching() -> None:
    truth = {"call_amount": "150000.00"}
    extracted = {"call_amount": "150000.0"}

    assert compare_document(truth, extracted)["exact_match"] is True


def test_compare_document_reports_a_missing_extracted_field_as_a_mismatch() -> None:
    truth = {"purpose": "New platform acquisition"}

    result = compare_document(truth, {})

    assert result["exact_match"] is False
    assert result["mismatches"][0]["extracted"] is None


def test_run_eval_summarizes_across_documents(tmp_path) -> None:
    manifests_dir = tmp_path / "manifests"
    extracted_dir = tmp_path / "extracted"
    manifests_dir.mkdir()
    (extracted_dir / "FUND-A").mkdir(parents=True)

    manifest = {
        "fund_id": "FUND-A",
        "documents": [
            {
                "name": "capital_call_01.pdf",
                "type": "capital_call",
                "injections": [],
                "fields": {"fund_id": "FUND-A", "call_amount": "150000.00"},
            },
            {
                "name": "capital_call_02.pdf",
                "type": "capital_call",
                "injections": [{"defect": "AMOUNT_TRANSPOSITION"}],
                "fields": {"fund_id": "FUND-A", "call_amount": "510000.00"},
            },
            # No extraction file exists for this one — the "not extracted" path.
            {
                "name": "capital_call_03.pdf",
                "type": "capital_call",
                "injections": [],
                "fields": {"fund_id": "FUND-A", "call_amount": "1.00"},
            },
        ],
    }
    (manifests_dir / "FUND-A.json").write_text(json.dumps(manifest))
    (extracted_dir / "FUND-A" / "capital_call_01.extracted.json").write_text(
        json.dumps({"fields": {"call_amount": "150000.00"}, "confidence": 0.9})
    )
    (extracted_dir / "FUND-A" / "capital_call_02.extracted.json").write_text(
        json.dumps({"fields": {"call_amount": "999999.00"}, "confidence": 0.9})
    )

    report = run_eval(manifests_dir, extracted_dir)

    assert report["document_count"] == 3
    assert report["extracted_count"] == 2
    assert report["document_exact_match_rate"] == 0.5
    assert report["field_accuracy"] == 0.5
    assert any(not d["extracted"] for d in report["documents"])
    assert any(d.get("had_injected_defect") for d in report["documents"] if d["extracted"])
