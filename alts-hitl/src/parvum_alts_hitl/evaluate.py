"""Evaluates extraction accuracy against the generator's own ground truth —
each document's ``fields`` entry in its fund's manifest (the *as-rendered*,
possibly-corrupted values), not the clean book. Extraction's job is to
faithfully read what is actually printed on a document, defects and all;
reconciling or flagging a defect is deterministic validation's job (a later
slice), not extraction's — so this eval measures reading accuracy, not
defect-detection accuracy.

Not wired into per-PR CI: every run is a real, billed API call. A manual/
periodic target (``make alts-eval``), the same shape as ``export-gold``.
"""

import argparse
import json
from pathlib import Path

from parvum_alts_hitl.parsing import parse_decimal

_DECIMAL_FIELDS = frozenset(
    {
        "call_amount",
        "cumulative_called",
        "remaining_commitment",
        "distribution_amount",
        "cumulative_distributed",
        "beginning_balance",
        "contributions",
        "distributions",
        "management_fees",
        "realized_gain_loss",
        "unrealized_gain_loss",
        "ending_balance",
        "total_commitment",
        "unfunded_commitment",
    }
)
# Context the generator writes into `fields` but that isn't part of the
# per-document extraction ground truth being scored here (fund identity is
# already known from the directory the document landed in).
_IGNORED_FIELDS = frozenset({"fund_id"})


def _normalize(field: str, value: object) -> object:
    if value is None:
        return None
    if field in _DECIMAL_FIELDS:
        parsed = parse_decimal(value)
        return parsed if parsed is not None else str(value)
    return str(value).strip()


def compare_document(ground_truth: dict, extracted: dict) -> dict:
    scored_fields = [f for f in ground_truth if f not in _IGNORED_FIELDS]
    mismatches = [
        {"field": field, "expected": ground_truth[field], "extracted": extracted.get(field)}
        for field in scored_fields
        if _normalize(field, ground_truth[field]) != _normalize(field, extracted.get(field))
    ]
    return {
        "exact_match": not mismatches,
        "mismatches": mismatches,
        "field_count": len(scored_fields),
    }


def run_eval(manifest_dir: Path, extracted_dir: Path) -> dict:
    document_results = []
    for manifest_path in sorted(manifest_dir.glob("*.json")):
        manifest = json.loads(manifest_path.read_text())
        fund_id = manifest["fund_id"]
        for doc in manifest["documents"]:
            stem = Path(doc["name"]).stem
            extracted_path = extracted_dir / fund_id / f"{stem}.extracted.json"
            if not extracted_path.exists():
                document_results.append(
                    {"fund_id": fund_id, "document": doc["name"], "extracted": False}
                )
                continue
            extracted_record = json.loads(extracted_path.read_text())
            comparison = compare_document(doc["fields"], extracted_record["fields"])
            document_results.append(
                {
                    "fund_id": fund_id,
                    "document": doc["name"],
                    "doc_type": doc["type"],
                    "extracted": True,
                    "confidence": extracted_record["confidence"],
                    "had_injected_defect": bool(doc["injections"]),
                    **comparison,
                }
            )

    extracted_docs = [d for d in document_results if d["extracted"]]
    exact_matches = [d for d in extracted_docs if d["exact_match"]]
    total_fields = sum(d["field_count"] for d in extracted_docs)
    total_mismatches = sum(len(d["mismatches"]) for d in extracted_docs)

    return {
        "document_count": len(document_results),
        "extracted_count": len(extracted_docs),
        "document_exact_match_rate": (
            len(exact_matches) / len(extracted_docs) if extracted_docs else None
        ),
        "field_accuracy": (
            (total_fields - total_mismatches) / total_fields if total_fields else None
        ),
        "documents": document_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate alts extraction accuracy against generator ground truth."
    )
    parser.add_argument("--manifests", type=Path, default=Path("../data/alts/manifests"))
    parser.add_argument("--extracted", type=Path, default=Path("../data/alts/extracted"))
    parser.add_argument("--out", type=Path, default=Path("../data/alts/eval_report.json"))
    args = parser.parse_args()

    report = run_eval(args.manifests, args.extracted)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")

    match_rate = report["document_exact_match_rate"]
    field_rate = report["field_accuracy"]
    print(
        f"{report['extracted_count']}/{report['document_count']} documents extracted; "
        f"document exact-match rate "
        f"{'n/a' if match_rate is None else f'{match_rate:.1%}'}; "
        f"field accuracy {'n/a' if field_rate is None else f'{field_rate:.1%}'}"
    )


if __name__ == "__main__":
    main()
