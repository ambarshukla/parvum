"""row_to_review_item: the join query's typed row -> ReviewItem shaping.

The HTTP fetch itself reuses gold_source's already-tested convert_rows; what's
new here is the extra parsing convert_rows can't do — period_end as a plain
ISO string (silver stores it untyped) and fields_json as a JSON string.
"""

from datetime import date
from decimal import Decimal

from parvum_export.review_queue_source import ReviewItem, row_to_review_item


def test_a_capital_call_row_parses_period_end_as_none():
    row = (
        "FUND-PE01",
        "capital_call_02.pdf",
        "capital_call",
        2,
        None,
        '{"call_amount": "100000.00"}',
        Decimal("0.7000"),
        "cumulative_called mismatch",
    )
    item = row_to_review_item(row)
    assert item == ReviewItem(
        fund_id="FUND-PE01",
        document="capital_call_02.pdf",
        doc_type="capital_call",
        sequence_number=2,
        period_end=None,
        extracted_fields={"call_amount": "100000.00"},
        confidence=Decimal("0.7000"),
        validation_notes="cumulative_called mismatch",
    )


def test_a_capital_account_statement_row_parses_period_end_as_a_date():
    row = (
        "FUND-PE01",
        "statement_2026Q2.pdf",
        "capital_account_statement",
        None,
        "2026-06-30",
        '{"beginning_balance": "500000.00", "ending_balance": "525000.00"}',
        Decimal("0.5500"),
        "beginning balance does not match prior statement's ending balance",
    )
    item = row_to_review_item(row)
    assert item.period_end == date(2026, 6, 30)
    assert item.sequence_number is None
    assert item.extracted_fields == {
        "beginning_balance": "500000.00",
        "ending_balance": "525000.00",
    }
