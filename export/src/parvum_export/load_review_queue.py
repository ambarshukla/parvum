"""CLI: load documents silver routed to needs_review into the internal review queue.

Runs the same way export_gold.py does — locally against docker-compose,
from GitHub Actions against RDS. The serving app must have started once
against the target database first (Flyway owns the "internal" schema; this
tool only fills it).
"""

import argparse
import os
import sys

import psycopg

from parvum_export.databricks_auth import DatabricksAuthError, resolve_token
from parvum_export.gold_source import ExportError
from parvum_export.review_queue_loader import load_review_queue
from parvum_export.review_queue_source import fetch_needs_review

_LOCAL_DSN = "postgresql://parvum:parvum_local_dev@127.0.0.1:5432/parvum"
_INTERNAL_SCHEMA = "internal"


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
        items = fetch_needs_review(host, token, warehouse_id)

        with psycopg.connect(args.dsn) as connection:
            summary = load_review_queue(connection, _INTERNAL_SCHEMA, items)
            print(f"review queue: pending={summary['pending']}, stale={summary['stale']}")
    except (ExportError, DatabricksAuthError, psycopg.Error) as exc:
        sys.exit(f"review-queue load failed: {exc}")


if __name__ == "__main__":
    main()
