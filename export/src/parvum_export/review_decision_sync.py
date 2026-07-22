"""Writes decided-but-unsynced review decisions to local files for landing,
and marks them synced once the land succeeds.

The reverse leg of the fetch/land contract every external call in this
platform follows (D-051, applied in the other direction): Postgres is where
a human decision gets made, Databricks is where it has to end up to remain
the platform's system of record. A decision is only ever marked synced
*after* a real land succeeds — never optimistically — so a failed or
partial land is always safe to retry.
"""

import json
from pathlib import Path

from psycopg import Connection, sql

from parvum_export.review_decision_source import ReviewDecision


def decision_payload(decision: ReviewDecision) -> dict:
    """Pure -- the tested core of what gets landed for one decision."""
    return {
        "fund_id": decision.fund_id,
        "document": decision.document,
        "doc_type": decision.doc_type,
        "sequence_number": decision.sequence_number,
        "period_end": decision.period_end.isoformat() if decision.period_end else None,
        "status": decision.status,
        "final_fields": decision.decided_fields,
        "decided_at": decision.decided_at.isoformat(),
    }


def write_decision_files(decisions: tuple[ReviewDecision, ...], out_dir: Path) -> list[Path]:
    written = []
    for decision in decisions:
        fund_dir = out_dir / decision.fund_id
        fund_dir.mkdir(parents=True, exist_ok=True)
        path = fund_dir / f"{decision.document}.decision.json"
        path.write_text(
            json.dumps(decision_payload(decision), indent=2), encoding="utf-8", newline="\n"
        )
        written.append(path)
    return written


def mark_synced(connection: Connection, schema: str, decisions: tuple[ReviewDecision, ...]) -> int:
    if not decisions:
        return 0
    table = sql.Identifier(schema, "alts_review_queue")
    keys = sql.SQL(", ").join(sql.SQL("(%s, %s)") for _ in decisions)
    params = [x for d in decisions for x in (d.fund_id, d.document)]
    with connection.transaction():
        result = connection.execute(
            sql.SQL(
                "UPDATE {table} SET synced_at = now() WHERE (fund_id, document) IN ({keys})"
            ).format(table=table, keys=keys),
            params,
        )
    return result.rowcount
