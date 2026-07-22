"""Upserts needs_review alts documents into the internal review queue.

Unlike gold's truncate-and-reload (a projection that carries no state of its
own), alts_review_queue holds real human decisions — pending -> approved or
corrected — that a fresh load must never silently overwrite. A reload only
ever touches pending rows: it refreshes their extracted values (silver can
be rebuilt with corrected extractions before anyone reviews them) and
un-stales/re-stales the ``stale`` flag to match whether the document is
still in the fresh needs_review set. A pending row that fell out of that set
(fixed upstream, or now auto_accepts) is marked stale rather than deleted —
a human might already be looking at it, and "no longer needs review" is
itself worth surfacing rather than making the row vanish silently. Decided
rows are left alone either way; the audit trail already covers them.
"""

from psycopg import Connection, sql
from psycopg.types.json import Json

from parvum_export.review_queue_source import ReviewItem

_UPSERT = """
    INSERT INTO {table}
        (fund_id, document, doc_type, sequence_number, period_end,
         extracted_fields, confidence, validation_notes, stale)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false)
    ON CONFLICT (fund_id, document) DO UPDATE SET
        doc_type = EXCLUDED.doc_type,
        sequence_number = EXCLUDED.sequence_number,
        period_end = EXCLUDED.period_end,
        extracted_fields = EXCLUDED.extracted_fields,
        confidence = EXCLUDED.confidence,
        validation_notes = EXCLUDED.validation_notes,
        stale = false,
        loaded_at = now()
    WHERE {table}.status = 'pending'
"""


def load_review_queue(
    connection: Connection, schema: str, items: tuple[ReviewItem, ...]
) -> dict[str, int]:
    """Reload one schema's review queue from the given needs_review items.

    Returns a small summary for the caller to print: how many rows are
    pending-and-current, and how many pending rows are now stale.
    """
    table = sql.Identifier(schema, "alts_review_queue")

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(
                sql.SQL(_UPSERT).format(table=table),
                [
                    (
                        item.fund_id,
                        item.document,
                        item.doc_type,
                        item.sequence_number,
                        item.period_end,
                        Json(item.extracted_fields),
                        item.confidence,
                        item.validation_notes,
                    )
                    for item in items
                ],
            )

        if items:
            keep = sql.SQL(", ").join(sql.SQL("(%s, %s)") for _ in items)
            params: list = [x for item in items for x in (item.fund_id, item.document)]
            connection.execute(
                sql.SQL(
                    "UPDATE {table} SET stale = true "
                    "WHERE status = 'pending' AND (fund_id, document) NOT IN ({keep})"
                ).format(table=table, keep=keep),
                params,
            )
        else:
            # Nothing needs review any more — every pending row is stale.
            connection.execute(
                sql.SQL("UPDATE {table} SET stale = true WHERE status = 'pending'").format(
                    table=table
                )
            )

        pending_current = connection.execute(
            sql.SQL("SELECT count(*) FROM {table} WHERE status = 'pending' AND NOT stale").format(
                table=table
            )
        ).fetchone()[0]
        pending_stale = connection.execute(
            sql.SQL("SELECT count(*) FROM {table} WHERE status = 'pending' AND stale").format(
                table=table
            )
        ).fetchone()[0]

    return {"pending": pending_current, "stale": pending_stale}
