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
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

GOLD_TABLES = (
    "gold_client_wealth",
    "gold_asset_allocation",
    "gold_income",
    "gold_top_holdings",
    "gold_ownership",
)


class ExportError(RuntimeError):
    """The export cannot proceed safely; nothing has been written."""


def _parse_timestamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
            raise ExportError(f"no converter for {column['name']}: {type_name}")
        converters.append(_CONVERTERS[type_name])
    rows = tuple(
        tuple(None if raw is None else fn(raw) for fn, raw in zip(converters, row, strict=True))
        for row in data
    )
    return names, rows


def fetch_table(host: str, token: str, warehouse_id: str, table: str) -> GoldTable:
    if table not in GOLD_TABLES:
        raise ExportError(f"not a gold table: {table}")
    body = {
        "warehouse_id": warehouse_id,
        "wait_timeout": "50s",
        "statement": f"SELECT * FROM workspace.parvum.{table}",
    }
    request = urllib.request.Request(
        host.rstrip("/") + "/api/2.0/sql/statements",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read())

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
