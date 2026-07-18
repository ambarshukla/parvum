"""Loader tests run against a real Postgres, migrated with the real DDL.

The schemas are created by applying the very same Flyway SQL files the
serving app uses (serving/src/main/resources/db/migration) — one source of
truth for the projection schema, exercised from both sides (D-029). Locally
that Postgres is the docker-compose one (`make up`); in CI it is a service
container. Unreachable Postgres skips these tests loudly rather than
failing them — the pure-Python tests still run everywhere.

Each test gets throwaway schemas with a unique suffix, so runs never
collide with each other or with real tenant schemas in the dev database.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

TEST_DSN = os.environ.get(
    "PARVUM_TEST_DSN", "postgresql://parvum:parvum_local_dev@127.0.0.1:5432/parvum"
)
_MIGRATIONS = (
    Path(__file__).parents[2] / "serving" / "src" / "main" / "resources" / "db" / "migration"
)


@pytest.fixture(scope="session")
def connection():
    try:
        conn = psycopg.connect(TEST_DSN, connect_timeout=3)
    except psycopg.OperationalError as exc:
        # Locally a missing database is an inconvenience; in CI the service
        # container is supposed to exist, so a skip would hide a real break.
        if os.environ.get("CI"):
            pytest.fail(f"CI Postgres service not reachable at {TEST_DSN}: {exc}")
        pytest.skip(f"Postgres not reachable at {TEST_DSN} — run `make up` ({exc})")
    with conn:
        yield conn


@pytest.fixture
def tenant_schemas(connection):
    """Two migrated throwaway schemas, dropped afterwards even on failure."""
    suffix = uuid.uuid4().hex[:8]
    schemas = (f"t_export_a_{suffix}", f"t_export_b_{suffix}")
    migrations = sorted(_MIGRATIONS.glob("V*.sql"))
    assert migrations, f"no Flyway migrations found under {_MIGRATIONS}"
    for schema in schemas:
        with connection.transaction():
            connection.execute(f'CREATE SCHEMA "{schema}"')
            # The DDL is unqualified by design (one set for every tenant);
            # search_path aims it at the schema under construction.
            connection.execute(f'SET LOCAL search_path TO "{schema}"')
            for migration in migrations:
                connection.execute(migration.read_text(encoding="utf-8"))
    yield schemas
    for schema in schemas:
        with connection.transaction():
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
