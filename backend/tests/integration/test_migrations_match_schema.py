"""The Alembic revisions build exactly what `docs/schema.sql` builds (skill `db-migration`).

`docs/schema.sql` is the complete schema; each revision runs its own reviewed SQL. Upgrading to
head must give the same columns (type, nullability, default), constraints and indexes as running
`docs/schema.sql` on an empty database, and a downgrade must give back the previous revision's
catalog. Column order is deliberately not compared: PostgreSQL appends added columns and cannot
reorder them, so nothing may rely on positional column order. Comments, triggers, functions and
sequences are not compared; the schema has none of its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command

from tests.integration.databases import fresh_database_url, psycopg_url
from tests.integration.test_initial_migration import _alembic

BACKEND = Path(__file__).resolve().parents[2]
SCHEMA_SQL = BACKEND.parent / "docs" / "schema.sql"
INITIAL_SQL = BACKEND / "migrations" / "sql" / "0001_initial.sql"
SCHEMAS = ["asset", "ledger", "prices", "portfolio", "processing", "platform"]

COLUMNS = """
SELECT table_schema, table_name, column_name, data_type, numeric_precision, numeric_scale,
       character_maximum_length, is_nullable, column_default
FROM information_schema.columns WHERE table_schema = ANY(%s)
"""
CONSTRAINTS = """
SELECT n.nspname, t.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = ANY(%s)
"""
INDEXES = (
    "SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = ANY(%s)"
)

database = contextmanager(fresh_database_url)


@pytest.fixture
def database_url() -> Iterator[str]:
    with database() as url:
        yield url


def catalog(database_url: str) -> dict[str, set[tuple[Any, ...]]]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return {
            name: {tuple(row) for row in connection.execute(query, (SCHEMAS,))}
            for name, query in (
                ("columns", COLUMNS),
                ("constraints", CONSTRAINTS),
                ("indexes", INDEXES),
            )
        }


def execute(database_url: str, sql: str) -> None:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(sql)


def fetch(database_url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return [tuple(row) for row in connection.execute(query)]


def _catalog_of_sql(sql: str) -> dict[str, set[tuple[Any, ...]]]:
    with database() as url:
        execute(url, sql)
        return catalog(url)


def test_upgrade_to_head_builds_exactly_the_documented_schema(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")

    migrated = catalog(database_url)
    documented = _catalog_of_sql(SCHEMA_SQL.read_text())
    for part in ("columns", "constraints", "indexes"):
        assert migrated[part] == documented[part], part


def test_downgrade_to_0001_gives_back_the_initial_schema(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    command.downgrade(_alembic(database_url), "0001")

    downgraded = catalog(database_url)
    initial = _catalog_of_sql(INITIAL_SQL.read_text())
    for part in ("columns", "constraints", "indexes"):
        assert downgraded[part] == initial[part], part
