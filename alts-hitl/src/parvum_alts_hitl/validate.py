"""Cross-document validation for alts extractions — the checks a single
document's self-consistency (``extract.py``) structurally cannot make,
because they need a whole fund's documents together: commitment
continuity, call/distribution sequencing, and capital-account statement
chaining. Pure logic, shared between the Databricks silver notebook
(``spark/silver_alts_documents.py``, orchestration only) and this
package's tests — the notebook imports this the same way
``bronze_alts_ingest.py`` already imports ``naming.py``.

This never *corrects* a value — it only decides whether the extracted
values reconcile with each other, and routes the document accordingly.
Fixing a flagged document is the human reviewer's job (a later slice), not
this one's.
"""

from decimal import Decimal

from parvum_alts_hitl.parsing import parse_decimal

# Below this hybrid confidence, a document is routed to review regardless
# of whether it happens to reconcile — a document the model itself wasn't
# sure about deserves a human look even if the numbers add up by
# coincidence.
CONFIDENCE_THRESHOLD = 0.85


def _sequence_notes(actual: list, expected: list, label: str) -> list[str]:
    return [] if actual == expected else [f"{label} sequence is {actual}, expected {expected}"]


def validate_calls(docs: list[dict]) -> list[dict]:
    """Each ``doc`` needs a ``fields`` dict (extracted values). Sequence
    must be gap-free from 1, and each call's ``cumulative_called`` must
    equal the running sum of ``call_amount`` up to and including it — both
    computed from the EXTRACTED values, never the clean book (this checks
    that the *extraction* is internally consistent across documents, not
    that the fund performed as originally modeled)."""
    ordered = sorted(docs, key=lambda d: d["fields"].get("call_number") or 0)
    actual_numbers = [d["fields"].get("call_number") for d in ordered]
    expected_numbers = list(range(1, len(ordered) + 1))

    results = []
    running = Decimal(0)
    for i, doc in enumerate(ordered):
        amount = parse_decimal(doc["fields"].get("call_amount"))
        cumulative = parse_decimal(doc["fields"].get("cumulative_called"))
        notes = _sequence_notes(actual_numbers, expected_numbers, "call")
        if amount is None or cumulative is None:
            notes.append("call_amount or cumulative_called missing/unparseable")
        else:
            running += amount
            if running != cumulative:
                notes.append(f"cumulative_called {cumulative} != running sum {running}")
        results.append(
            {
                **doc,
                "cross_document_valid": not notes,
                "validation_notes": "; ".join(notes) or None,
                "sequence_number": actual_numbers[i],
                "period_end": None,
            }
        )
    return results


def validate_distributions(docs: list[dict]) -> list[dict]:
    ordered = sorted(docs, key=lambda d: d["fields"].get("distribution_number") or 0)
    actual_numbers = [d["fields"].get("distribution_number") for d in ordered]
    expected_numbers = list(range(1, len(ordered) + 1))

    results = []
    running = Decimal(0)
    for i, doc in enumerate(ordered):
        amount = parse_decimal(doc["fields"].get("distribution_amount"))
        cumulative = parse_decimal(doc["fields"].get("cumulative_distributed"))
        notes = _sequence_notes(actual_numbers, expected_numbers, "distribution")
        if amount is None or cumulative is None:
            notes.append("distribution_amount or cumulative_distributed missing/unparseable")
        else:
            running += amount
            if running != cumulative:
                notes.append(f"cumulative_distributed {cumulative} != running sum {running}")
        results.append(
            {
                **doc,
                "cross_document_valid": not notes,
                "validation_notes": "; ".join(notes) or None,
                "sequence_number": actual_numbers[i],
                "period_end": None,
            }
        )
    return results


def validate_statements(docs: list[dict]) -> list[dict]:
    """Each statement's ``beginning_balance`` must equal the prior
    statement's ``ending_balance`` — the chaining invariant ``book.py``
    built the clean data to satisfy; this checks the EXTRACTED numbers
    still satisfy it."""
    ordered = sorted(docs, key=lambda d: d["fields"].get("period_end") or "")

    results = []
    prior_ending: Decimal | None = None
    for doc in ordered:
        beginning = parse_decimal(doc["fields"].get("beginning_balance"))
        ending = parse_decimal(doc["fields"].get("ending_balance"))
        notes = []
        if beginning is None or ending is None:
            notes.append("beginning_balance or ending_balance missing/unparseable")
        elif prior_ending is not None and beginning != prior_ending:
            notes.append(f"beginning_balance {beginning} != prior ending_balance {prior_ending}")
        results.append(
            {
                **doc,
                "cross_document_valid": not notes,
                "validation_notes": "; ".join(notes) or None,
                "sequence_number": None,
                "period_end": doc["fields"].get("period_end"),
            }
        )
        if ending is not None:
            prior_ending = ending
    return results


_VALIDATORS = {
    "capital_call": validate_calls,
    "distribution": validate_distributions,
    "capital_account_statement": validate_statements,
}


def route(doc: dict) -> str:
    structurally_valid = bool(doc["self_consistent"]) and bool(doc["cross_document_valid"])
    if structurally_valid and doc["confidence"] >= CONFIDENCE_THRESHOLD:
        return "auto_accept"
    return "needs_review"


def validate_fund_documents(docs: list[dict]) -> list[dict]:
    """Validates one fund's documents (mixed doc types) and adds a
    ``routing`` decision to each. Each input dict needs ``doc_type``,
    ``fields``, ``self_consistent``, and ``confidence``."""
    by_type: dict[str, list[dict]] = {}
    for doc in docs:
        by_type.setdefault(doc["doc_type"], []).append(doc)

    validated = []
    for doc_type, type_docs in by_type.items():
        validator = _VALIDATORS.get(doc_type)
        if validator is None:
            validated.extend(
                {
                    **doc,
                    "cross_document_valid": False,
                    "validation_notes": f"unknown doc_type: {doc_type}",
                    "sequence_number": None,
                    "period_end": None,
                }
                for doc in type_docs
            )
            continue
        validated.extend(validator(type_docs))

    for doc in validated:
        doc["routing"] = route(doc)
    return validated
