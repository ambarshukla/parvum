"""Cross-document validation. Each test demonstrates a specific break being
caught, per this project's standing rule: data-quality logic needs a test
that shows a seeded break actually gets flagged, not just that the happy
path passes."""

from parvum_alts_hitl.validate import (
    CONFIDENCE_THRESHOLD,
    route,
    validate_calls,
    validate_distributions,
    validate_fund_documents,
    validate_statements,
)


def _call(number: int, amount: str, cumulative: str) -> dict:
    return {
        "document": f"capital_call_{number:02d}.pdf",
        "doc_type": "capital_call",
        "fields": {"call_number": number, "call_amount": amount, "cumulative_called": cumulative},
    }


def _distribution(number: int, amount: str, cumulative: str) -> dict:
    return {
        "document": f"distribution_{number:02d}.pdf",
        "doc_type": "distribution",
        "fields": {
            "distribution_number": number,
            "distribution_amount": amount,
            "cumulative_distributed": cumulative,
        },
    }


def _statement(period_end: str, beginning: str, ending: str) -> dict:
    return {
        "document": f"capital_account_{period_end}.pdf",
        "doc_type": "capital_account_statement",
        "fields": {
            "period_end": period_end,
            "beginning_balance": beginning,
            "ending_balance": ending,
        },
    }


class TestValidateCalls:
    def test_a_clean_sequence_is_valid(self) -> None:
        docs = [
            _call(1, "150000.00", "150000.00"),
            _call(2, "200000.00", "350000.00"),
            _call(3, "150000.00", "500000.00"),
        ]
        results = validate_calls(docs)
        assert all(r["cross_document_valid"] for r in results)
        assert all(r["validation_notes"] is None for r in results)

    def test_catches_a_cumulative_called_mismatch(self) -> None:
        # Call 2's cumulative_called is wrong: should be 350000.00, says 351000.00
        # (this is exactly what the COMMITMENT_MISMATCH generator defect produces).
        docs = [
            _call(1, "150000.00", "150000.00"),
            _call(2, "200000.00", "351000.00"),
        ]
        results = validate_calls(docs)
        by_number = {r["sequence_number"]: r for r in results}
        assert by_number[1]["cross_document_valid"] is True
        assert by_number[2]["cross_document_valid"] is False
        assert "cumulative_called" in by_number[2]["validation_notes"]

    def test_catches_a_sequence_gap(self) -> None:
        # Call #2 is missing entirely (e.g. a dropped document).
        docs = [_call(1, "150000.00", "150000.00"), _call(3, "150000.00", "450000.00")]
        results = validate_calls(docs)
        assert all(not r["cross_document_valid"] for r in results)
        assert all("sequence" in r["validation_notes"] for r in results)

    def test_catches_a_transposed_amount_via_the_cumulative_check(self) -> None:
        # call_amount transposed (750000.00 -> 570000.00, the AMOUNT_TRANSPOSITION
        # shape) breaks the running-sum check even though nothing else is wrong.
        docs = [_call(1, "570000.00", "750000.00")]
        results = validate_calls(docs)
        assert results[0]["cross_document_valid"] is False


class TestValidateDistributions:
    def test_a_clean_sequence_is_valid(self) -> None:
        docs = [_distribution(1, "25000.00", "25000.00"), _distribution(2, "40000.00", "65000.00")]
        results = validate_distributions(docs)
        assert all(r["cross_document_valid"] for r in results)

    def test_catches_a_cumulative_distributed_mismatch(self) -> None:
        docs = [_distribution(1, "25000.00", "25000.00"), _distribution(2, "40000.00", "99999.00")]
        results = validate_distributions(docs)
        assert results[1]["cross_document_valid"] is False


class TestValidateStatements:
    def test_a_chained_series_is_valid(self) -> None:
        docs = [
            _statement("2024-03-31", "0.00", "145000.00"),
            _statement("2024-06-30", "145000.00", "340000.00"),
        ]
        results = validate_statements(docs)
        assert all(r["cross_document_valid"] for r in results)

    def test_catches_a_broken_chain(self) -> None:
        # Second statement's beginning_balance doesn't match the first's
        # ending_balance — exactly what an ARITHMETIC_ERROR defect on either
        # statement would produce downstream.
        docs = [
            _statement("2024-03-31", "0.00", "145000.00"),
            _statement("2024-06-30", "145500.00", "340000.00"),
        ]
        results = validate_statements(docs)
        assert results[0]["cross_document_valid"] is True
        assert results[1]["cross_document_valid"] is False
        assert "beginning_balance" in results[1]["validation_notes"]

    def test_the_first_statement_has_no_prior_to_chain_against(self) -> None:
        docs = [_statement("2024-03-31", "999999.00", "145000.00")]
        assert validate_statements(docs)[0]["cross_document_valid"] is True


class TestRoute:
    def test_auto_accepts_when_everything_checks_out(self) -> None:
        doc = {
            "self_consistent": True,
            "cross_document_valid": True,
            "confidence": CONFIDENCE_THRESHOLD,
        }
        assert route(doc) == "auto_accept"

    def test_needs_review_when_confidence_is_below_threshold(self) -> None:
        doc = {
            "self_consistent": True,
            "cross_document_valid": True,
            "confidence": CONFIDENCE_THRESHOLD - 0.01,
        }
        assert route(doc) == "needs_review"

    def test_needs_review_when_cross_document_check_fails_even_with_high_confidence(self) -> None:
        doc = {"self_consistent": True, "cross_document_valid": False, "confidence": 0.99}
        assert route(doc) == "needs_review"

    def test_needs_review_when_self_consistency_fails_even_with_high_confidence(self) -> None:
        doc = {"self_consistent": False, "cross_document_valid": True, "confidence": 0.99}
        assert route(doc) == "needs_review"


class TestValidateFundDocuments:
    def test_mixed_doc_types_are_each_validated_and_routed(self) -> None:
        docs = [
            {**_call(1, "150000.00", "150000.00"), "self_consistent": True, "confidence": 0.95},
            {
                **_statement("2024-03-31", "0.00", "145000.00"),
                "self_consistent": True,
                "confidence": 0.95,
            },
        ]
        results = validate_fund_documents(docs)
        assert {r["doc_type"] for r in results} == {"capital_call", "capital_account_statement"}
        assert all(r["routing"] == "auto_accept" for r in results)

    def test_an_unknown_doc_type_is_routed_to_review_not_silently_dropped(self) -> None:
        docs = [
            {
                "document": "mystery.pdf",
                "doc_type": "side_letter",
                "fields": {},
                "self_consistent": True,
                "confidence": 0.99,
            }
        ]
        results = validate_fund_documents(docs)
        assert results[0]["cross_document_valid"] is False
        assert results[0]["routing"] == "needs_review"
