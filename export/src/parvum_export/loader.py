"""Loads gold rows into a tenant schema: truncate-and-reload, one transaction.

Truncate-and-reload (D-029) because gold itself is a full rebuild carrying
complete history: mirroring it exactly beats merging into it — an upsert that
never deletes would silently keep rows a gold restatement removed. One
transaction per tenant, so readers see the old projection or the new one,
never an empty table.

Column lists come from the fetched manifest and must match the Flyway DDL by
name; a drift between lakehouse and serving schemas fails loudly at INSERT
rather than loading misaligned data.
"""

from psycopg import Connection, sql

from parvum_export.gold_source import GoldTable

# gold table → its projection table in every tenant schema (the Flyway DDL).
PROJECTION_TABLES = {
    "gold_client_wealth": "client_wealth",
    "gold_asset_allocation": "asset_allocation",
    "gold_income": "income",
    "gold_top_holdings": "top_holdings",
    "gold_ownership": "ownership",
}


def load_tenant(connection: Connection, schema: str, tables: list[GoldTable]) -> dict[str, int]:
    """Reload one tenant schema from the given (already filtered) tables.

    Returns table → rows loaded, for the caller's summary.
    """
    counts: dict[str, int] = {}
    with connection.transaction():
        for table in tables:
            target = PROJECTION_TABLES[table.name]
            qualified = sql.Identifier(schema, target)
            connection.execute(sql.SQL("TRUNCATE TABLE {}").format(qualified))
            if table.rows:
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    qualified,
                    sql.SQL(", ").join(sql.Identifier(name) for name in table.columns),
                    sql.SQL(", ").join(sql.Placeholder() for _ in table.columns),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(statement, table.rows)
            counts[target] = len(table.rows)
    return counts
