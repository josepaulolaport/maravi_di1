"""What every migration test shares: an Alembic config, a fresh database and a catalog reader.

Each migration test upgrades or downgrades its own throwaway database (CLAUDE.md §4), so it
never touches a shared one. The test modules re-export ``database_url`` for pytest to find it.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config

from tests.integration.databases import fresh_database_url, psycopg_url

BACKEND = Path(__file__).resolve().parents[2]
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


def alembic_config(database_url: str, *x_arguments: str) -> Config:
    """The project's Alembic config pointed at ``database_url``, with ``-x`` arguments."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # configparser interpolates `%`; a percent-encoded password must survive.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.cmd_opts = Namespace(x=list(x_arguments))
    return config


def execute(database_url: str, sql: str) -> None:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(sql)


def fetch(database_url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return [tuple(row) for row in connection.execute(query)]


def catalog(database_url: str) -> dict[str, set[tuple[Any, ...]]]:
    """The columns, constraints and indexes of the project's schemas."""
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return {
            name: {tuple(row) for row in connection.execute(query, (SCHEMAS,))}
            for name, query in (
                ("columns", COLUMNS),
                ("constraints", CONSTRAINTS),
                ("indexes", INDEXES),
            )
        }
