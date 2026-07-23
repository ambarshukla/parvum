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
    "alts_usd",
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


PERFORMANCE_COLUMNS = (
    "as_of",
    "client_id",
    "client_name",
    "total_wealth_usd",
    "external_flow_usd",
    "daily_twr_return",
    "twr_index_since_inception",
    "rebuilt_at",
)


def performance_row(client_id: str, day: date, twr_return: str | None, index: str) -> tuple:
    return (
        day,
        client_id,
        f"{client_id} name",
        Decimal("1000000.00"),
        Decimal("0.00"),
        Decimal(twr_return) if twr_return is not None else None,
        Decimal(index),
        REBUILT,
    )


def performance_table(*rows: tuple) -> GoldTable:
    return GoldTable(name="gold_performance", columns=PERFORMANCE_COLUMNS, rows=rows)


PERFORMANCE_SUMMARY_COLUMNS = (
    "client_id",
    "client_name",
    "inception_date",
    "as_of",
    "wealth_begin_usd",
    "wealth_end_usd",
    "net_external_flow_usd",
    "twr_since_inception",
    "dietz_since_inception",
    "irr_since_inception_annualized",
    "rebuilt_at",
)


def performance_summary_row(
    client_id: str, inception: date, as_of: date, twr: str, dietz: str | None, irr: str | None
) -> tuple:
    return (
        client_id,
        f"{client_id} name",
        inception,
        as_of,
        Decimal("1000000.00"),
        Decimal("1050000.00"),
        Decimal("25000.00"),
        Decimal(twr),
        Decimal(dietz) if dietz is not None else None,
        Decimal(irr) if irr is not None else None,
        REBUILT,
    )


def performance_summary_table(*rows: tuple) -> GoldTable:
    return GoldTable(
        name="gold_performance_summary", columns=PERFORMANCE_SUMMARY_COLUMNS, rows=rows
    )


ALTS_HOLDINGS_COLUMNS = (
    "client_id",
    "client_name",
    "fund_id",
    "fund_name",
    "account_id",
    "inception_date",
    "as_of",
    "total_commitment_usd",
    "called_to_date_usd",
    "distributed_to_date_usd",
    "unfunded_commitment_usd",
    "current_nav_usd",
    "moic",
    "pending_review_documents",
    "rebuilt_at",
    "currency",
)


def alts_holding_row(
    client_id: str,
    fund_id: str,
    inception: date | None,
    as_of: date | None,
    called: str,
    moic: str | None,
    pending: int,
    currency: str = "USD",
) -> tuple:
    return (
        client_id,
        f"{client_id} name",
        fund_id,
        f"{fund_id} name",
        "ACC-1",
        inception,
        as_of,
        Decimal("5000000.00"),
        Decimal(called),
        Decimal("100000.00"),
        Decimal("4900000.00"),
        Decimal("1200000.00"),
        Decimal(moic) if moic is not None else None,
        pending,
        REBUILT,
        currency,
    )


def alts_holdings_table(*rows: tuple) -> GoldTable:
    return GoldTable(name="gold_alts_holdings", columns=ALTS_HOLDINGS_COLUMNS, rows=rows)


DQ_METRICS_COLUMNS = ("as_of", "dimension", "metric", "value", "passed", "detail", "rebuilt_at")


def dq_metric_row(day: date, dimension: str, metric: str, value: str, passed: bool | None) -> tuple:
    return (day, dimension, metric, Decimal(value), passed, f"{metric} detail", REBUILT)


def dq_metrics_table(*rows: tuple) -> GoldTable:
    return GoldTable(name="dq_metrics", columns=DQ_METRICS_COLUMNS, rows=rows)


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
        # Inserted here, not appended at the end: the tests below slice
        # empty_other_tables() from the tail (e.g. [:-3]) to override the last
        # few tables while keeping the rest empty. Adding a new table has to
        # go somewhere that doesn't change how many elements those negative
        # offsets from the end skip over.
        alts_holdings_table(),
        GoldTable(name="gold_income", columns=income_columns, rows=()),
        GoldTable(name="gold_top_holdings", columns=holdings_columns, rows=()),
        dq_metrics_table(),
        performance_table(),
        performance_summary_table(),
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


def test_alts_holdings_load_with_nullable_fields_intact(connection, tenant_schemas):
    schema, _ = tenant_schemas
    # A fund with a confirmed statement (dates and moic present) alongside
    # one with nothing confirmed yet (inception_date/as_of/moic all NULL,
    # per gold_reports.py's fallback when no capital account statement has
    # been reviewed) -- the loader must not choke on either shape.
    holdings = alts_holdings_table(
        alts_holding_row(
            "CLI-HARTWELL",
            "FUND-VC01",
            date(2024, 3, 31),
            date(2026, 6, 30),
            "1200000.00",
            "1.10",
            0,
        ),
        alts_holding_row("CLI-REYES", "FUND-PE01", None, None, "0.00", None, 2),
    )
    others = [t for t in empty_other_tables() if t.name != "gold_alts_holdings"]
    counts = load_tenant(connection, schema, [wealth_table(), holdings, *others])
    assert counts["alts_holdings"] == 2

    stored = connection.execute(
        f"SELECT client_id, inception_date, as_of, moic, pending_review_documents "
        f'FROM "{schema}".alts_holdings ORDER BY client_id'
    ).fetchall()
    assert stored == [
        ("CLI-HARTWELL", date(2024, 3, 31), date(2026, 6, 30), Decimal("1.10"), 0),
        ("CLI-REYES", None, None, None, 2),
    ]


def test_performance_series_and_summary_load_with_nulls_intact(connection, tenant_schemas):
    schema, _ = tenant_schemas
    # Inception day carries no return (NULL) — the same boundary rule
    # PERFORMANCE_METHODOLOGY.md documents; the loader must not choke on it,
    # and it must round-trip through Postgres as NULL, not a sentinel.
    series = performance_table(
        performance_row("CLI-HARTWELL", date(2026, 4, 20), None, "1.00000000"),
        performance_row("CLI-HARTWELL", date(2026, 7, 17), "-0.01305400", "0.92463372"),
    )
    summary = performance_summary_table(
        performance_summary_row(
            "CLI-HARTWELL",
            date(2026, 4, 20),
            date(2026, 7, 17),
            "-0.04489876",
            "-0.04488757",
            "-0.17344373",
        )
    )
    counts = load_tenant(
        connection,
        schema,
        [wealth_table(), *empty_other_tables()[:-3], series, summary, ownership_table()],
    )
    assert counts["performance"] == 2
    assert counts["performance_summary"] == 1

    first_return = connection.execute(
        f'SELECT daily_twr_return FROM "{schema}".performance ORDER BY as_of LIMIT 1'
    ).fetchone()
    assert first_return == (None,)

    summary_row = connection.execute(
        f"SELECT twr_since_inception, dietz_since_inception, irr_since_inception_annualized "
        f'FROM "{schema}".performance_summary'
    ).fetchone()
    assert summary_row == (
        Decimal("-0.04489876"),
        Decimal("-0.04488757"),
        Decimal("-0.17344373"),
    )


def test_dq_metrics_loads_unfiltered_with_null_passed_intact(connection, tenant_schemas):
    schema, _ = tenant_schemas
    # dq_metrics carries no client_id -- export_gold.py loads it into every
    # tenant schema unfiltered (UNSCOPED_TABLES). The exceptions row's
    # passed=NULL is the interesting case: trend data, not pass/fail.
    metrics = dq_metrics_table(
        dq_metric_row(date(2026, 6, 30), "completeness", "files_landed_rate", "1.000000", True),
        dq_metric_row(date(2026, 6, 30), "exceptions", "holdings_findings_count", "3.000000", None),
    )
    counts = load_tenant(
        connection,
        schema,
        [
            wealth_table(),
            *empty_other_tables()[:-4],
            metrics,
            performance_table(),
            performance_summary_table(),
            ownership_table(),
        ],
    )
    assert counts["dq_metrics"] == 2
    stored = connection.execute(
        f'SELECT dimension, value, passed FROM "{schema}".dq_metrics ORDER BY dimension'
    ).fetchall()
    assert stored == [
        ("completeness", Decimal("1.000000"), True),
        ("exceptions", Decimal("3.000000"), None),
    ]
