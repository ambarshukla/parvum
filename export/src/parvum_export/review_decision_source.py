"""Reads decided-but-unsynced alts review decisions from the internal
Postgres queue — the read half of the reverse-sync job D-051 promised and
deferred, D-054 built the forward loader for.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from psycopg import Connection, sql


@dataclass(frozen=True)
class ReviewDecision:
    fund_id: str
    document: str
    doc_type: str
    sequence_number: int | None
    period_end: date | None
    status: str
    decided_fields: dict[str, Any]
    decided_at: datetime


def fetch_unsynced_decisions(connection: Connection, schema: str) -> tuple[ReviewDecision, ...]:
    """Every approved/corrected row with no synced_at yet — the exact set
    the reverse-sync job needs to land."""
    table = sql.Identifier(schema, "alts_review_queue")
    rows = connection.execute(
        sql.SQL(
            "SELECT fund_id, document, doc_type, sequence_number, period_end, "
            "status, decided_fields, decided_at FROM {table} "
            "WHERE status IN ('approved', 'corrected') AND synced_at IS NULL "
            "ORDER BY decided_at"
        ).format(table=table)
    ).fetchall()
    return tuple(ReviewDecision(*row) for row in rows)
