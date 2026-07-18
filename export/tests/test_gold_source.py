"""Conversion from the SQL Statements API wire shape, pinned against a live
probe of the real gold tables (values arrive as strings + typed manifest)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from parvum_export.gold_source import ExportError, GoldTable, convert_rows

WEALTH_SCHEMA = [
    {"name": "as_of", "type_name": "DATE"},
    {"name": "client_id", "type_name": "STRING"},
    {"name": "total_wealth_usd", "type_name": "DECIMAL"},
    {"name": "books_reconcile", "type_name": "BOOLEAN"},
    {"name": "rebuilt_at", "type_name": "TIMESTAMP"},
    {"name": "movements", "type_name": "LONG"},
]

WIRE_ROW = ["2026-07-17", "CLI-REYES", "1694300.83", "false", "2026-07-18T09:50:30.134Z", "18"]


def test_wire_strings_become_typed_values():
    columns, rows = convert_rows(WEALTH_SCHEMA, [WIRE_ROW])
    assert columns == (
        "as_of",
        "client_id",
        "total_wealth_usd",
        "books_reconcile",
        "rebuilt_at",
        "movements",
    )
    assert rows == (
        (
            date(2026, 7, 17),
            "CLI-REYES",
            Decimal("1694300.83"),
            False,
            datetime(2026, 7, 18, 9, 50, 30, 134000, tzinfo=UTC),
            18,
        ),
    )


def test_decimal_conversion_is_exact_not_float():
    _, rows = convert_rows([{"name": "v", "type_name": "DECIMAL"}], [["1.143500"]])
    assert rows[0][0] == Decimal("1.143500")
    assert str(rows[0][0]) == "1.143500"


def test_nulls_survive_conversion():
    _, rows = convert_rows(WEALTH_SCHEMA, [[None] * len(WEALTH_SCHEMA)])
    assert rows == ((None,) * len(WEALTH_SCHEMA),)


def test_unknown_wire_type_is_a_loud_stop():
    with pytest.raises(ExportError, match="INTERVAL"):
        convert_rows([{"name": "v", "type_name": "INTERVAL"}], [])


def test_filtered_keeps_only_the_tenants_clients():
    table = GoldTable(
        name="gold_client_wealth",
        columns=("client_id", "total_wealth_usd"),
        rows=(("CLI-HARTWELL", 1), ("CLI-OKAFOR", 2), ("CLI-REYES", 3)),
    )
    filtered = table.filtered({"CLI-OKAFOR", "CLI-REYES"})
    assert filtered.rows == (("CLI-OKAFOR", 2), ("CLI-REYES", 3))
    assert table.client_ids() == {"CLI-HARTWELL", "CLI-OKAFOR", "CLI-REYES"}
