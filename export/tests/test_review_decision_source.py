"""fetch_unsynced_decisions against a real Postgres migrated with the real
migration_internal DDL.

What a green run proves: only approved/corrected rows with no synced_at
come back — a pending row, and an already-synced decided row, are both
correctly excluded.
"""

from parvum_export.review_decision_source import fetch_unsynced_decisions


def seed(connection, schema, document, status, synced=False):
    decided = status != "pending"
    connection.execute(
        f'INSERT INTO "{schema}".alts_review_queue '
        "(fund_id, document, doc_type, sequence_number, period_end, extracted_fields, "
        " confidence, status, decided_fields, decided_at, synced_at) "
        "VALUES ('FUND-PE01', %s, 'capital_call', 2, null, "
        '\'{"call_amount": "100000.00"}\'::jsonb, 0.700, %s, '
        + ('\'{"call_amount": "100000.00"}\'::jsonb, now()' if decided else "null, null")
        + ", "
        + ("now()" if synced else "null")
        + ")",
        (document, status),
    )


def test_only_unsynced_decided_rows_are_returned(connection, internal_schema):
    seed(connection, internal_schema, "call_pending.pdf", "pending")
    seed(connection, internal_schema, "call_approved_unsynced.pdf", "approved", synced=False)
    seed(connection, internal_schema, "call_corrected_unsynced.pdf", "corrected", synced=False)
    seed(connection, internal_schema, "call_already_synced.pdf", "approved", synced=True)

    decisions = fetch_unsynced_decisions(connection, internal_schema)
    documents = {d.document for d in decisions}
    assert documents == {"call_approved_unsynced.pdf", "call_corrected_unsynced.pdf"}


def test_decision_fields_round_trip(connection, internal_schema):
    seed(connection, internal_schema, "call_02.pdf", "corrected", synced=False)
    (decision,) = fetch_unsynced_decisions(connection, internal_schema)
    assert decision.fund_id == "FUND-PE01"
    assert decision.doc_type == "capital_call"
    assert decision.status == "corrected"
    assert decision.decided_fields == {"call_amount": "100000.00"}
    assert decision.decided_at is not None
