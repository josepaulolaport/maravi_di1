"""Revision 0002: cash and positions as two separately processable chains (OQ-21).

- 0001 + 0002 build exactly the database `docs/schema.sql` builds: same columns (type,
  nullability, default), constraints and indexes.
- Existing rows are carried over: requests get scope ALL; the ledger revision and the accounting
  marker seed both new revisions and both new markers; published cash, which has no components,
  is dropped, AUM becomes unavailable and cash is stale from the first published day.
- Downgrade to 0001 restores 0001's database exactly, and refuses while it would lose rows unless
  ``-x allow_data_loss=true`` is given.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
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


_database = contextmanager(fresh_database_url)


@pytest.fixture
def database_url() -> Iterator[str]:
    with _database() as url:
        yield url


def _catalog(database_url: str) -> dict[str, set[tuple[Any, ...]]]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return {
            name: {tuple(row) for row in connection.execute(query, (SCHEMAS,))}
            for name, query in (
                ("columns", COLUMNS),
                ("constraints", CONSTRAINTS),
                ("indexes", INDEXES),
            )
        }


def _execute(database_url: str, sql: str) -> None:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(sql)


def _fetch(database_url: str, query: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return [tuple(row) for row in connection.execute(query)]


def test_the_revisions_build_exactly_the_documented_schema(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    with _database() as documented_url:
        _execute(documented_url, SCHEMA_SQL.read_text())
        documented = _catalog(documented_url)

    migrated = _catalog(database_url)
    for part in ("columns", "constraints", "indexes"):
        assert migrated[part] == documented[part], part


def test_upgrade_carries_existing_rows_over(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "0001")
    _execute(
        database_url,
        "INSERT INTO processing.requests (requested_start_date, requested_end_date,"
        " ledger_revision_at_start) VALUES ('2026-10-01', '2026-10-05', 7);"
        "UPDATE processing.calculation_state SET ledger_revision = 7,"
        " accounting_dirty_from = '2026-10-10';"
        "INSERT INTO portfolio.portfolio_metrics (metric_date, cash_balance,"
        " positions_market_value, aum, valuation_status, pnl_status)"
        " VALUES ('2026-10-03', 100, 50, 150, 'COMPLETE', 'COMPLETE');",
    )

    command.upgrade(_alembic(database_url), "head")

    requests = _fetch(
        database_url,
        "SELECT scope, trades_revision_at_start, cash_movements_revision_at_start"
        " FROM processing.requests",
    )
    state = _fetch(
        database_url,
        "SELECT trades_revision, cash_movements_revision, cash_dirty_from, positions_dirty_from"
        " FROM processing.calculation_state",
    )
    metrics = _fetch(
        database_url, "SELECT positions_market_value, aum FROM portfolio.portfolio_metrics"
    )
    assert requests == [("ALL", 7, 7)]
    assert state == [(7, 7, date(2026, 10, 3), date(2026, 10, 10))]
    assert [(str(value), aum) for value, aum in metrics] == [("50", None)]


def test_downgrade_restores_the_initial_schema(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    command.downgrade(_alembic(database_url), "0001")
    with _database() as initial_url:
        _execute(initial_url, INITIAL_SQL.read_text())
        initial = _catalog(initial_url)

    downgraded = _catalog(database_url)
    for part in ("columns", "constraints", "indexes"):
        assert downgraded[part] == initial[part], part


def test_downgrade_refuses_to_lose_published_cash(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    _execute(
        database_url,
        "INSERT INTO portfolio.cash_balances VALUES ('2026-10-01', 100, 0, 100, 0)",
    )

    with pytest.raises(RuntimeError, match="allow_data_loss"):
        command.downgrade(_alembic(database_url), "0001")
    command.downgrade(_alembic(database_url, "allow_data_loss=true"), "0001")

    tables = _fetch(
        database_url,
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'cash_balances'",
    )
    assert tables == [(0,)]
