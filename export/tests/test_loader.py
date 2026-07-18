"""Truncate-and-reload against a real Postgres migrated with the real DDL.

What a green run proves: rows land where the tenant mapping says, tenants
cannot see each other's data, a reload after a gold restatement leaves no
ghost rows, and the projection tables' shape (the Flyway DDL) accepts what
the gold manifest sends — schema drift between the two sides fails here.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from parvum_export.gold_source import GoldTable
from parvum_export.loader import load_tenant

REBUILT = datetime(2026, 7, 18, 9, 50, 30, tzinfo=UTC)

WEALTH_COLUMNS = (
    "as_of",
    "client_id",
    "client_name",
    "positions_usd",
    "cash_usd",
    "total_wealth_usd",
    "fx_rate_used",
    "fx_rate_date",
    "books_reconcile",
    "rebuilt_at",
)


def wealth_row(client_id: str, day: date, total: str) -> tuple:
    return (
        day,
        client_id,
        f"{client_id} name",
        Decimal(total),
        Decimal("0.00"),
        Decimal(total),
        Decimal("1.143500"),
        day,
        True,
        REBUILT,
    )


def wealth_table(*rows: tuple) -> GoldTable:
    return GoldTable(name="gold_client_wealth", columns=WEALTH_COLUMNS, rows=rows)


OWNERSHIP_COLUMNS = (
    "account_id",
    "client_id",
    "client_name",
    "ownership_pct",
    "owner_count",
    "is_shared",
    "rebuilt_at",
)


def ownership_row(account_id: str, client_id: str, pct: str, owners: int) -> tuple:
    return (
        account_id,
        client_id,
        f"{client_id} name",
        Decimal(pct),
        owners,
        owners > 1,
        REBUILT,
    )


def ownership_table(*rows: tuple) -> GoldTable:
    return GoldTable(name="gold_ownership", columns=OWNERSHIP_COLUMNS, rows=rows)


def empty_other_tables() -> list[GoldTable]:
    income_columns = (
        "client_id",
        "client_name",
        "month",
        "type",
        "income_usd",
        "movements",
        "rebuilt_at",
    )
    holdings_columns = (
        "as_of",
        "client_id",
        "client_name",
        "rank",
        "security_name",
        "security_scheme",
        "security_id",
        "asset_class",
        "owned_usd",
        "weight",
        "rebuilt_at",
    )
    allocation_columns = (
        "as_of",
        "client_id",
        "client_name",
        "asset_class",
        "value_usd",
        "weight",
        "rebuilt_at",
    )
    return [
        GoldTable(name="gold_asset_allocation", columns=allocation_columns, rows=()),
        GoldTable(name="gold_income", columns=income_columns, rows=()),
        GoldTable(name="gold_top_holdings", columns=holdings_columns, rows=()),
        ownership_table(),
    ]


def count(connection, schema: str, table: str) -> int:
    return connection.execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()[0]


def test_tenants_only_see_their_own_rows(connection, tenant_schemas):
    schema_a, schema_b = tenant_schemas
    hartwell = wealth_table(wealth_row("CLI-HARTWELL", date(2026, 7, 17), "41090000.00"))
    stonefield = wealth_table(
        wealth_row("CLI-OKAFOR", date(2026, 7, 17), "2870000.00"),
        wealth_row("CLI-REYES", date(2026, 7, 17), "1694300.83"),
    )
    counts_a = load_tenant(connection, schema_a, [hartwell, *empty_other_tables()])
    counts_b = load_tenant(connection, schema_b, [stonefield, *empty_other_tables()])

    assert counts_a["client_wealth"] == 1
    assert counts_b["client_wealth"] == 2
    clients_a = {
        row[0]
        for row in connection.execute(
            f'SELECT client_id FROM "{schema_a}".client_wealth'
        ).fetchall()
    }
    assert clients_a == {"CLI-HARTWELL"}


def test_reload_after_restatement_leaves_no_ghost_rows(connection, tenant_schemas):
    schema, _ = tenant_schemas
    two_days = wealth_table(
        wealth_row("CLI-HARTWELL", date(2026, 7, 16), "41000000.00"),
        wealth_row("CLI-HARTWELL", date(2026, 7, 17), "41090000.00"),
    )
    load_tenant(connection, schema, [two_days, *empty_other_tables()])
    assert count(connection, schema, "client_wealth") == 2

    # Gold restated: the 16th vanished upstream. The projection must follow.
    one_day = wealth_table(wealth_row("CLI-HARTWELL", date(2026, 7, 17), "41090000.00"))
    load_tenant(connection, schema, [one_day, *empty_other_tables()])
    remaining = connection.execute(f'SELECT as_of FROM "{schema}".client_wealth').fetchall()
    assert remaining == [(date(2026, 7, 17),)]


def test_reload_is_idempotent(connection, tenant_schemas):
    schema, _ = tenant_schemas
    table = wealth_table(wealth_row("CLI-HARTWELL", date(2026, 7, 17), "41090000.00"))
    load_tenant(connection, schema, [table, *empty_other_tables()])
    load_tenant(connection, schema, [table, *empty_other_tables()])
    assert count(connection, schema, "client_wealth") == 1


def test_typed_values_round_trip_through_postgres(connection, tenant_schemas):
    schema, _ = tenant_schemas
    day = date(2026, 7, 17)
    load_tenant(
        connection,
        schema,
        [wealth_table(wealth_row("CLI-REYES", day, "1694300.83")), *empty_other_tables()],
    )
    stored = connection.execute(
        f"SELECT total_wealth_usd, fx_rate_used, books_reconcile, rebuilt_at "
        f'FROM "{schema}".client_wealth'
    ).fetchone()
    assert stored[0] == Decimal("1694300.83")
    assert stored[1] == Decimal("1.143500")
    assert stored[2] is True
    assert stored[3] == REBUILT


def test_ownership_graph_loads_the_shared_account(connection, tenant_schemas):
    schema, _ = tenant_schemas
    # The 60/40 account, both edges routed to one tenant (as tenants.py arranges).
    owners = ownership_table(
        ownership_row("ACC-SHARED", "CLI-REYES", "0.600000", 2),
        ownership_row("ACC-SHARED", "CLI-OKAFOR", "0.400000", 2),
    )
    counts = load_tenant(
        connection,
        schema,
        [wealth_table(), *empty_other_tables()[:-1], owners],
    )
    assert counts["ownership"] == 2
    stored = connection.execute(
        f"SELECT client_id, ownership_pct, owner_count, is_shared "
        f'FROM "{schema}".ownership ORDER BY ownership_pct DESC'
    ).fetchall()
    assert stored == [
        ("CLI-REYES", Decimal("0.600000"), 2, True),
        ("CLI-OKAFOR", Decimal("0.400000"), 2, True),
    ]
