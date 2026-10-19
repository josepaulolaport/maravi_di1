"""Upgrade to head creates the schema of `docs/schema.sql`; downgrade to base removes it (plan §3).

- 0001 + 0002 build exactly what `docs/schema.sql` builds (checked column by column in
  `test_cash_chain_migration.py`).
- Upgrade to head on a fresh PostgreSQL 16 database creates the six schemas and 21 tables, with
  the singleton `processing.calculation_state` row. Downgrade to base removes them, and a second
  upgrade works again.
- Downgrade refuses to drop a database that holds business data unless ``-x allow_data_loss=true``
  is given: it is meant for fresh or throwaway databases only.
- An async caller migrates through its own connection (``connection.run_sync``).

The database tests need ``TEST_DATABASE_URL`` (an admin URL, e.g.
``postgresql+psycopg://postgres:x@localhost:55432/postgres``); each test creates and drops its own
database, so it never touches a shared one.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.databases import fresh_database_url, psycopg_url

BACKEND = Path(__file__).resolve().parents[2]

SCHEMAS = {"asset", "ledger", "prices", "portfolio", "processing", "platform"}
TABLES = {
    "asset.instrument_types", "asset.asset_classes", "asset.products", "asset.futures",
    "asset.instruments", "ledger.trades", "ledger.cash_movements", "prices.reference_prices",
    "processing.requests", "processing.calculation_state", "processing.issues",
    "portfolio.positions", "portfolio.position_metrics", "portfolio.portfolio_metrics",
    "portfolio.staged_positions", "portfolio.staged_position_metrics",
    "portfolio.staged_portfolio_metrics", "portfolio.cash_balances",
    "portfolio.staged_cash_balances", "platform.outbox_messages", "platform.inbox_messages",
}  # fmt: skip


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from fresh_database_url()


def _alembic(database_url: str, *x_arguments: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # configparser interpolates `%`; a percent-encoded password must survive.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.cmd_opts = Namespace(x=list(x_arguments))
    return config


def test_database_url_with_percent_encoding_survives_the_config() -> None:
    url = "postgresql+psycopg://user:p%40ss%25w@localhost:5432/db"
    assert _alembic(url).get_main_option("sqlalchemy.url") == url


def _schemas_and_tables(database_url: str) -> tuple[set[str], set[str], int | None]:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        schemas = {
            row[0]
            for row in connection.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)",
                (sorted(SCHEMAS),),
            )
        }
        tables = {
            f"{row[0]}.{row[1]}"
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
                (sorted(SCHEMAS),),
            )
        }
        singleton = None
        if "processing.calculation_state" in tables:
            row = connection.execute("SELECT count(*) FROM processing.calculation_state").fetchone()
            singleton = row[0] if row else None
    return schemas, tables, singleton


# Each result is stored before it is asserted, so a failure never prints the URL (password).


def test_upgrade_creates_the_documented_schema(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")

    state = _schemas_and_tables(database_url)
    assert state == (SCHEMAS, TABLES, 1)


def test_downgrade_removes_everything_and_upgrade_works_again(database_url: str) -> None:
    config = _alembic(database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "base")
    state = _schemas_and_tables(database_url)
    assert state == (set(), set(), None)

    command.upgrade(config, "head")
    state = _schemas_and_tables(database_url)
    assert state == (SCHEMAS, TABLES, 1)


def _insert_cash_movement(database_url: str) -> None:
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(
            "INSERT INTO ledger.cash_movements (movement_date, movement_type, amount) "
            "VALUES ('2026-10-16', 'DEPOSIT', 400000)"
        )


def test_downgrade_refuses_to_drop_business_data(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    _insert_cash_movement(database_url)

    with pytest.raises(RuntimeError, match="allow_data_loss"):
        command.downgrade(_alembic(database_url), "base")
    state = _schemas_and_tables(database_url)
    assert state == (SCHEMAS, TABLES, 1)


def test_downgrade_drops_business_data_only_when_explicitly_allowed(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")
    _insert_cash_movement(database_url)

    command.downgrade(_alembic(database_url, "allow_data_loss=true"), "base")
    state = _schemas_and_tables(database_url)
    assert state == (set(), set(), None)


async def test_async_caller_migrates_through_its_own_connection(database_url: str) -> None:
    config = _alembic(database_url)

    def upgrade(connection: Connection) -> None:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()
    state = _schemas_and_tables(database_url)
    assert state == (SCHEMAS, TABLES, 1)
