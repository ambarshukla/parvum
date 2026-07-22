"""Upsert-and-flag against a real Postgres migrated with the real
migration_internal DDL.

What a green run proves: a fresh needs_review set lands as pending rows, a
reload refreshes still-pending rows in place, a decided row is never
touched by a reload no matter what the fresh fetch says, and a pending row
that drops out of the fresh set is flagged stale rather than deleted (and
un-staled if it reappears).
"""

from datetime import date
from decimal import Decimal

from parvum_export.review_queue_loader import load_review_queue
from parvum_export.review_queue_source import ReviewItem


def call_item(document: str, confidence: str, notes: str | None = "cascading defect") -> ReviewItem:
    return ReviewItem(
        fund_id="FUND-PE01",
        document=document,
        doc_type="capital_call",
        sequence_number=2,
        period_end=None,
        extracted_fields={"call_amount": "100000.00"},
        confidence=Decimal(confidence),
        validation_notes=notes,
    )


def fetch_row(connection, schema, document, *columns):
    return connection.execute(
        f'SELECT {", ".join(columns)} FROM "{schema}".alts_review_queue WHERE document = %s',
        (document,),
    ).fetchone()


def test_a_fresh_needs_review_item_loads_as_pending_and_not_stale(connection, internal_schema):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    row = fetch_row(connection, internal_schema, "call_02.pdf", "status", "stale", "confidence")
    assert row == ("pending", False, Decimal("0.700"))


def test_reload_refreshes_a_still_pending_row(connection, internal_schema):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    # Silver got rebuilt with a corrected extraction before anyone reviewed it.
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.950", None),))
    row = fetch_row(connection, internal_schema, "call_02.pdf", "confidence", "validation_notes")
    assert row == (Decimal("0.950"), None)


def test_a_decided_row_is_never_touched_by_a_reload(connection, internal_schema):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    connection.execute(
        f'UPDATE "{internal_schema}".alts_review_queue '
        "SET status = 'approved', decided_fields = extracted_fields, decided_at = now() "
        "WHERE document = %s",
        ("call_02.pdf",),
    )

    # The fresh fetch still (implausibly) reports it as needs_review — must not matter.
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.950", None),))
    row = fetch_row(connection, internal_schema, "call_02.pdf", "status", "confidence", "stale")
    assert row == ("approved", Decimal("0.700"), False)

    # And the fresh fetch no longer reporting it must not touch it either.
    load_review_queue(connection, internal_schema, ())
    row = fetch_row(connection, internal_schema, "call_02.pdf", "status", "stale")
    assert row == ("approved", False)


def test_a_pending_row_dropped_from_the_fresh_set_is_flagged_stale_not_deleted(
    connection, internal_schema
):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    summary = load_review_queue(connection, internal_schema, ())
    row = fetch_row(connection, internal_schema, "call_02.pdf", "status", "stale")
    assert row == ("pending", True)
    assert summary == {"pending": 0, "stale": 1}


def test_a_stale_row_that_reappears_is_un_staled(connection, internal_schema):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    load_review_queue(connection, internal_schema, ())  # dropped -> stale
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))  # back
    row = fetch_row(connection, internal_schema, "call_02.pdf", "status", "stale")
    assert row == ("pending", False)


def test_extracted_fields_round_trip_as_jsonb(connection, internal_schema):
    load_review_queue(connection, internal_schema, (call_item("call_02.pdf", "0.700"),))
    row = fetch_row(connection, internal_schema, "call_02.pdf", "extracted_fields")
    assert row == ({"call_amount": "100000.00"},)


def test_period_end_and_sequence_number_round_trip_including_null(connection, internal_schema):
    statement = ReviewItem(
        fund_id="FUND-PE01",
        document="statement_2026Q2.pdf",
        doc_type="capital_account_statement",
        sequence_number=None,
        period_end=date(2026, 6, 30),
        extracted_fields={"ending_balance": "525000.00"},
        confidence=Decimal("0.550"),
        validation_notes=None,
    )
    load_review_queue(connection, internal_schema, (statement,))
    row = fetch_row(
        connection, internal_schema, "statement_2026Q2.pdf", "sequence_number", "period_end"
    )
    assert row == (None, date(2026, 6, 30))
