"""(Re)create the Unity Catalog metric views in this directory on the lakehouse.

Metric views are Unity Catalog objects, not Delta tables, so the bronze -> gold
job does not build them. This script applies every ``*.sql`` file here through
the SQL Statements API — the same pull-not-push path the freshness gate and the
exporter already use — so the definition stays in git, reviewable, and
re-appliable after a workspace rebuild.

Usage::

    python spark/metric_views/apply.py          # apply every *.sql in this dir
    make metric-views                           # same, with the DATABRICKS_HOST guard

Auth: ``DATABRICKS_HOST`` from the environment, plus either ``DATABRICKS_TOKEN``
or a cached CLI login (``databricks auth token``). ``DATABRICKS_WAREHOUSE_ID``
selects the warehouse (defaults to the project's serverless starter).

Statement splitting is deliberately naive — statements are separated by ``;`` at
end of line, and neither the ``$$ ... $$`` YAML body nor the COMMENT strings
here contain one. Keep it that way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_WAREHOUSE_ID = "0fb6ed828ed1e874"


def _token(host: str) -> str:
    tok = os.environ.get("DATABRICKS_TOKEN")
    if tok:
        return tok
    out = subprocess.run(
        ["databricks", "auth", "token", "--host", host],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)["access_token"]


def _statements(sql_text: str) -> list[str]:
    """Split a .sql file into runnable statements, dropping comment-only lines."""
    out: list[str] = []
    for chunk in sql_text.split(";\n"):
        lines = chunk.splitlines()
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
            lines.pop(0)
        stmt = "\n".join(lines).strip().rstrip(";").strip()
        if stmt:
            out.append(stmt)
    return out


def _run(host: str, token: str, warehouse_id: str, statement: str) -> None:
    body = json.dumps(
        {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "30s"}
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/2.0/sql/statements",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
    state = result.get("status", {}).get("state")
    if state != "SUCCEEDED":
        json.dump(result, sys.stderr, indent=2)
        sys.stderr.write("\n")
        raise SystemExit(f"statement did not succeed (state={state})")


def main() -> None:
    host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    if not host:
        raise SystemExit("DATABRICKS_HOST not set — copy .env.example to .env and fill it in")
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", DEFAULT_WAREHOUSE_ID)
    token = _token(host)

    sql_files = sorted(HERE.glob("*.sql"))
    if not sql_files:
        raise SystemExit(f"no *.sql files in {HERE}")

    for sql_file in sql_files:
        statements = _statements(sql_file.read_text(encoding="utf-8"))
        print(f"{sql_file.name}: {len(statements)} statement(s)")
        for stmt in statements:
            print(f"  -> {stmt.splitlines()[0][:72]}")
            _run(host, token, warehouse_id, stmt)
    print("metric views applied")


if __name__ == "__main__":
    main()
