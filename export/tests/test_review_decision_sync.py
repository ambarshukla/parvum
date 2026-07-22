"""decision_payload and write_decision_files are pure (tmp_path); mark_synced
runs against a real Postgres migrated with the real migration_internal DDL.
"""

from datetime import UTC, date, datetime

from parvum_export.review_decision_source import ReviewDecision
from parvum_export.review_decision_sync import decision_payload, mark_synced, write_decision_files

DECIDED_AT = datetime(2026, 7, 22, 10, 30, 0, tzinfo=UTC)


def call_decision(document: str, status: str = "corrected") -> ReviewDecision:
    return ReviewDecision(
        fund_id="FUND-PE01",
        document=document,
        doc_type="capital_call",
        sequence_number=2,
        period_end=None,
        status=status,
        decided_fields={"call_amount": "100000.00"},
        decided_at=DECIDED_AT,
    )


def statement_decision(document: str) -> ReviewDecision:
    return ReviewDecision(
        fund_id="FUND-PE01",
        document=document,
        doc_type="capital_account_statement",
        sequence_number=None,
        period_end=date(2026, 6, 30),
        status="approved",
        decided_fields={"ending_balance": "525000.00"},
        decided_at=DECIDED_AT,
    )


def test_decision_payload_serializes_period_end_and_decided_at():
    payload = decision_payload(statement_decision("statement_2026Q2.pdf"))
    assert payload == {
        "fund_id": "FUND-PE01",
        "document": "statement_2026Q2.pdf",
        "doc_type": "capital_account_statement",
        "sequence_number": None,
        "period_end": "2026-06-30",
        "status": "approved",
        "final_fields": {"ending_balance": "525000.00"},
        "decided_at": "2026-07-22T10:30:00+00:00",
    }


def test_decision_payload_handles_a_null_period_end():
    payload = decision_payload(call_decision("call_02.pdf"))
    assert payload["period_end"] is None


def test_write_decision_files_lands_one_json_file_per_document(tmp_path):
    written = write_decision_files(
        (call_decision("call_02.pdf"), statement_decision("statement_2026Q2.pdf")), tmp_path
    )
    assert {p.relative_to(tmp_path).as_posix() for p in written} == {
        "FUND-PE01/call_02.pdf.decision.json",
        "FUND-PE01/statement_2026Q2.pdf.decision.json",
    }
    for path in written:
        assert path.exists()


def test_mark_synced_sets_synced_at_only_for_the_given_decisions(connection, internal_schema):
    for document in ("call_02.pdf", "call_03.pdf"):
        connection.execute(
            f'INSERT INTO "{internal_schema}".alts_review_queue '
            "(fund_id, document, doc_type, sequence_number, period_end, extracted_fields, "
            " confidence, status, decided_fields, decided_at) "
            "VALUES ('FUND-PE01', %s, 'capital_call', 2, null, "
            "'{\"call_amount\": \"100000.00\"}'::jsonb, 0.700, 'corrected', "
            '\'{"call_amount": "100000.00"}\'::jsonb, now())',
            (document,),
        )

    updated = mark_synced(connection, internal_schema, (call_decision("call_02.pdf"),))
    assert updated == 1

    rows = connection.execute(
        f'SELECT document, synced_at IS NOT NULL FROM "{internal_schema}".alts_review_queue '
        "ORDER BY document"
    ).fetchall()
    assert rows == [("call_02.pdf", True), ("call_03.pdf", False)]


def test_mark_synced_with_no_decisions_is_a_no_op(connection, internal_schema):
    assert mark_synced(connection, internal_schema, ()) == 0
