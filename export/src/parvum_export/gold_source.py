"""Reads the gold tables over the Databricks SQL Statements API.

Values arrive as strings with a typed manifest (probed live before this was
written: DATE ``2026-07-17``, DECIMAL ``1.143500``, BOOLEAN ``false``,
TIMESTAMP ``2026-07-18T09:50:30.134Z``); conversion happens here, once, so
the loader only ever sees proper Python values.

The whole gold layer is a few hundred rows, so a result must fit one inline
chunk; more than one means the data has outgrown this design, which should
be a loud stop rather than a silently truncated export.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from parvum_export.sql_api import ExportError, post_statement

GOLD_TABLES = (
    "gold_client_wealth",
    "gold_asset_allocation",
    "gold_income",
    "gold_top_holdings",
    "gold_ownership",
    "gold_performance",
    "gold_performance_summary",
    "gold_alts_holdings",
    "gold_reconciliation_exceptions",
)

# Tables that carry no client_id — a fact about the whole pipeline (D-043),
# not about any one firm's clients. Fetched the same way as GOLD_TABLES, but
# never filtered by tenant: export_gold.py loads the same rows into every
# tenant schema (see V4__dq_metrics.sql for why that's the deliberate
# tradeoff, not an oversight).
UNSCOPED_TABLES = ("dq_metrics", "governance_cde_registry", "dq_slo_attainment")

SOURCE_TABLES = GOLD_TABLES + UNSCOPED_TABLES


def _parse_timestamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# The set is deliberately closed: an unfamiliar wire type stops the export
# rather than being guessed at, because a silently mis-typed column reaches a
# client screen looking like a number.
#
# **DOUBLE is absent on purpose, and it is the one people will want to add.**
# This estate is Decimal end to end (D-029) — money compared at the cent, and
# fractions that must round-trip exactly. Mapping DOUBLE to `float` would let a
# binary approximation into a column that lands in `numeric`, and mapping it to
# `Decimal` would preserve the approximation while looking exact. The right fix
# when this fires is to CAST at the source, in the Spark job that publishes the
# column — which is what `governance_cde_registry.slo_attainment_objective`
# does, after this guard caught it publishing a DOUBLE.
_CONVERTERS = {
    "STRING": str,
    "INT": int,
    "LONG": int,
    "DECIMAL": Decimal,
    "DATE": date.fromisoformat,
    "TIMESTAMP": _parse_timestamp,
    "BOOLEAN": lambda raw: raw == "true",
}


@dataclass(frozen=True)
class GoldTable:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    def filtered(self, client_ids: set[str]) -> "GoldTable":
        """The same table reduced to one tenant's clients."""
        index = self.columns.index("client_id")
        return GoldTable(
            name=self.name,
            columns=self.columns,
            rows=tuple(row for row in self.rows if row[index] in client_ids),
        )

    def client_ids(self) -> set[str]:
        index = self.columns.index("client_id")
        return {row[index] for row in self.rows}


def convert_rows(
    schema_columns: list[dict], data: list[list[str | None]]
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    """Apply the manifest's types to the raw string rows. Pure — the tested core."""
    names = tuple(column["name"] for column in schema_columns)
    converters = []
    for column in schema_columns:
        type_name = column["type_name"]
        if type_name not in _CONVERTERS:
            raise ExportError(
                f"no converter for {column['name']}: {type_name}. The converter set is "
                f"closed on purpose — fix this by CASTing the column in the Spark job "
                f"that publishes it, not by widening the set here "
                f"(known: {', '.join(sorted(_CONVERTERS))})"
            )
        converters.append(_CONVERTERS[type_name])
    rows = tuple(
        tuple(None if raw is None else fn(raw) for fn, raw in zip(converters, row, strict=True))
        for row in data
    )
    return names, rows


def fetch_table(host: str, token: str, warehouse_id: str, table: str) -> GoldTable:
    if table not in SOURCE_TABLES:
        raise ExportError(f"not a known source table: {table}")
    body = {
        "warehouse_id": warehouse_id,
        "wait_timeout": "50s",
        "statement": f"SELECT * FROM workspace.parvum.{table}",
    }
    result = post_statement(host, token, body, what=f"reading {table}")

    state = result.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise ExportError(
            f"query on {table} did not succeed: {json.dumps(result.get('status'))[:300]}"
        )
    manifest = result["manifest"]
    if manifest.get("total_chunk_count", 1) > 1:
        raise ExportError(
            f"{table} no longer fits one inline result chunk "
            f"({manifest.get('total_row_count')} rows) — the exporter needs chunked reads now"
        )
    columns, rows = convert_rows(
        manifest["schema"]["columns"], result.get("result", {}).get("data_array") or []
    )
    return GoldTable(name=table, columns=columns, rows=rows)
