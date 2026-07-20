"""Integration check: run validate.py against the *real* generator output
(via generate.generate(), not hand-picked fixtures), simulating faithful
extraction — fields = the manifest's own as-rendered ground truth, and
self_consistent computed the same way extract.py really computes it
(extract.self_consistency_ok against those same fields), not hardcoded.
So any flag raised here is attributable only to the extract/validate
pipeline's own logic catching a real generator defect, not to test noise.

Two rounds of this test caught two real modeling mistakes in the test
itself before it caught what it was meant to catch:

1. "No injected defect -> never flagged" was wrong: a running-sum check
   cascades. If call #1's amount is corrupted, every later call's
   cumulative_called check also stops tying out, even though calls #2-4
   are individually clean — the *correct*, honest behavior of a real
   running-total check, not a false positive.
2. Hardcoding self_consistent=True was wrong: a faithfully-extracted
   statement whose own printed numbers don't reconcile (ARITHMETIC_ERROR)
   should compute self_consistent=False via extract.py's own check — that
   defect is caught there, not by validate.py's cross-document chaining,
   which only compares beginning_balance to the *prior* statement's
   ending_balance and has no reason to notice a single statement's
   internal arithmetic being wrong.

The corrected test asserts on the combined `routing` decision (what
actually matters operationally) rather than on which of the two
mechanisms did the catching.
"""

from parvum_alts_hitl.extract import self_consistency_ok
from parvum_alts_hitl.generate import generate
from parvum_alts_hitl.validate import validate_fund_documents

# Every defect type that corrupts a field either self_consistency_ok or
# validate.py's chaining checks inspect. MISSING_FIELD only nulls
# purpose/source, which neither mechanism looks at, so it's deliberately
# excluded — a document with only that defect is expected to auto_accept.
_DETECTABLE = {"COMMITMENT_MISMATCH", "AMOUNT_TRANSPOSITION", "ARITHMETIC_ERROR"}

_SEQUENCE_KEY = {
    "capital_call": lambda fields: fields.get("call_number"),
    "distribution": lambda fields: fields.get("distribution_number"),
    "capital_account_statement": lambda fields: fields.get("period_end"),
}


def test_validate_catches_every_generator_defect_it_is_designed_to_catch(tmp_path) -> None:
    manifests = generate(tmp_path / "raw")

    for manifest in manifests:
        docs = [
            {
                "document": d["name"],
                "doc_type": d["type"],
                "fields": d["fields"],
                "self_consistent": self_consistency_ok(d["type"], d["fields"]),
                "confidence": 1.0,
                "had_defect": bool({i["defect"] for i in d["injections"]} & _DETECTABLE),
            }
            for d in manifest["documents"]
        ]
        results = {r["document"]: r for r in validate_fund_documents(docs)}

        # Chaining checks cascade: mark every document from the first
        # defect onward (in its type's own sequence) as "tainted" — only a
        # document strictly before any defect in its chain can be asserted
        # clean.
        by_type: dict[str, list[dict]] = {}
        for doc in docs:
            by_type.setdefault(doc["doc_type"], []).append(doc)

        for doc_type, type_docs in by_type.items():
            ordered = sorted(type_docs, key=lambda d: _SEQUENCE_KEY[doc_type](d["fields"]))
            tainted = False
            for doc in ordered:
                result = results[doc["document"]]
                if doc["had_defect"] or not doc["self_consistent"]:
                    assert result["routing"] == "needs_review", (
                        f"{doc['document']} has a detectable defect but was auto_accepted "
                        f"(self_consistent={doc['self_consistent']}, "
                        f"cross_document_valid={result['cross_document_valid']})"
                    )
                    tainted = True
                elif not tainted:
                    assert result["routing"] == "auto_accept", (
                        f"{doc['document']} has no defect (own or upstream) but was flagged: "
                        f"{result['validation_notes']}"
                    )
                # else: downstream of an earlier defect — a cascaded flag is
                # expected and correct, not asserted either way here.
