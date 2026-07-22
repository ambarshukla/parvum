"""CLI: land decided-but-unsynced alts review decisions into the Databricks
volume, then mark them synced in Postgres.

Runs the same way load_review_queue.py does — locally against docker-
compose, from GitHub Actions against RDS — but needs the `databricks` CLI
on PATH too (for `fs cp`), not just API/DB reachability, since this is a
file upload rather than a SQL Statements API call.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg

from parvum_export.review_decision_source import fetch_unsynced_decisions
from parvum_export.review_decision_sync import mark_synced, write_decision_files

_LOCAL_DSN = "postgresql://parvum:parvum_local_dev@127.0.0.1:5432/parvum"
_INTERNAL_SCHEMA = "internal"
_VOLUME_PATH = "dbfs:/Volumes/workspace/parvum/landing/alts/reviewed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dsn",
        default=os.environ.get("PARVUM_PG_DSN", _LOCAL_DSN),
        help="Postgres DSN (default: $PARVUM_PG_DSN, else the docker-compose database)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("../data/alts/reviewed"),
        help="local staging directory for landed decision files",
    )
    args = parser.parse_args()

    try:
        with psycopg.connect(args.dsn) as connection:
            decisions = fetch_unsynced_decisions(connection, _INTERNAL_SCHEMA)
            if not decisions:
                print("nothing to sync")
                return

            write_decision_files(decisions, args.out)
            result = subprocess.run(
                ["databricks", "fs", "cp", "-r", str(args.out), _VOLUME_PATH, "--overwrite"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                sys.exit(f"land failed, nothing marked synced: {result.stderr.strip()}")

            synced = mark_synced(connection, _INTERNAL_SCHEMA, decisions)
            print(f"synced {synced} decision(s) to {_VOLUME_PATH}")
    except psycopg.Error as exc:
        sys.exit(f"review-decision sync failed: {exc}")


if __name__ == "__main__":
    main()
