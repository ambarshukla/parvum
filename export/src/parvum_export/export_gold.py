"""CLI: pull the gold tables, split per tenant, reload each tenant schema.

Runs wherever there is open egress to both Databricks and Postgres: locally
against the docker-compose database today, from GitHub Actions against RDS
once the AWS leg exists (D-029). The serving app must have started once
against the target database first — Flyway owns the schemas; this tool only
fills them.

A client id in gold that no tenant claims aborts the run before anything is
written: a new family must be assigned a firm (tenants.py) before it can be
served, otherwise its data would silently reach nobody.
"""

import argparse
import os
import sys

import psycopg

from parvum_export.databricks_auth import DatabricksAuthError, resolve_token
from parvum_export.gold_source import GOLD_TABLES, UNSCOPED_TABLES, ExportError, fetch_table
from parvum_export.loader import load_tenant
from parvum_export.tenants import TENANT_CLIENTS, client_tenants, schema_for

_LOCAL_DSN = "postgresql://parvum:parvum_local_dev@127.0.0.1:5432/parvum"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dsn",
        default=os.environ.get("PARVUM_PG_DSN", _LOCAL_DSN),
        help="Postgres DSN (default: $PARVUM_PG_DSN, else the docker-compose database)",
    )
    args = parser.parse_args()

    host = os.environ.get("DATABRICKS_HOST", "").strip()
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if not (host and warehouse_id):
        sys.exit("DATABRICKS_HOST and DATABRICKS_WAREHOUSE_ID must be set — see .env.example")

    try:
        token = resolve_token(host)
        tables = [fetch_table(host, token, warehouse_id, table) for table in GOLD_TABLES]
        # No client_id to filter by — a fact about the pipeline, not about any
        # one firm's clients, so the same rows load into every tenant as-is.
        unscoped = [fetch_table(host, token, warehouse_id, table) for table in UNSCOPED_TABLES]

        owners = client_tenants()
        seen = set().union(*(table.client_ids() for table in tables))
        if unclaimed := sorted(seen - owners.keys()):
            raise ExportError(
                f"gold contains clients no tenant claims: {', '.join(unclaimed)} — "
                "assign them a firm in tenants.py before exporting"
            )

        with psycopg.connect(args.dsn) as connection:
            for tenant_id, client_ids in TENANT_CLIENTS.items():
                filtered = [table.filtered(set(client_ids)) for table in tables]
                counts = load_tenant(connection, schema_for(tenant_id), filtered + unscoped)
                summary = ", ".join(f"{table}={count}" for table, count in counts.items())
                print(f"{tenant_id}: {summary}")
    except (ExportError, DatabricksAuthError, psycopg.Error) as exc:
        sys.exit(f"export failed: {exc}")


if __name__ == "__main__":
    main()
