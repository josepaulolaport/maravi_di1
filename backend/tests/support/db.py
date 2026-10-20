"""Throwaway PostgreSQL databases for integration tests (CLAUDE.md §4: never a shared database).

``TEST_DATABASE_URL`` is an admin URL on a test server (SQLAlchemy form,
``postgresql+psycopg://user:password@host:port/postgres``). Each test gets a new database with a
unique name, dropped afterwards. Without the variable the database tests are skipped, and the
run reports them as skipped: they are then **not verified**. With ``REQUIRE_DATABASE_TESTS=1``
(set by ``make test-backend``) a missing variable fails the run instead, so a green run always
applied them.

A migrated database is a copy of one template, migrated to head once per test session
(``CREATE DATABASE … TEMPLATE``): the copy is the database ``alembic upgrade head`` gives, without
running the migrations again for every test. The migration tests themselves start from
`fresh_database_url`, an empty database.
"""

from __future__ import annotations

import os
import uuid
from argparse import Namespace
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import build_asset_service
from di1.modules.asset.domain.model import FuturesTerms
from di1.modules.asset.infrastructure.persistence.models import AssetClassRow, InstrumentTypeRow
from di1.modules.asset.public import Instrument
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.builders import (
    CATALOGUE,
    DI1_NAME,
    DI1F27,
    DI1F28,
    DI1F29,
    DI1F30,
    PRODUCT_ID,
)

BACKEND = Path(__file__).resolve().parents[2]

_template: str | None = None
"""The migrated template of this test session, created on first use (`drop_template`)."""


def psycopg_url(sqlalchemy_url: str) -> str:
    """The libpq form of a SQLAlchemy URL (``postgresql+psycopg://`` → ``postgresql://``)."""
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


def alembic_config(database_url: str, *x_arguments: str) -> Config:
    """The project's Alembic configuration, pointed at ``database_url``, with ``-x`` arguments."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # configparser interpolates `%`; a percent-encoded password must survive.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.cmd_opts = Namespace(x=list(x_arguments))
    return config


def execute(database_url: str, statement: str) -> None:
    """Run SQL on a test database, in one transaction."""
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(statement)


def fetch(database_url: str, query: str) -> list[tuple[Any, ...]]:
    """The rows of a query on a test database."""
    with psycopg.connect(psycopg_url(database_url)) as connection:
        return [tuple(row) for row in connection.execute(query)]


def _admin_url() -> str:
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        if os.environ.get("REQUIRE_DATABASE_TESTS") == "1":
            pytest.fail("REQUIRE_DATABASE_TESTS=1 but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL is not set: database tests not run")
    return admin_url


def _url_of(admin_url: str, name: str) -> str:
    return make_url(admin_url).set(database=name).render_as_string(hide_password=False)


def _execute(admin_url: str, statement: sql.Composed) -> None:
    with psycopg.connect(psycopg_url(admin_url), autocommit=True) as admin:
        admin.execute(statement)


def _drop(admin_url: str, name: str) -> None:
    _execute(
        admin_url, sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
    )


def _database(template: str | None) -> Iterator[str]:
    admin_url = _admin_url()
    if template == "migrated":
        template = _migrated_template(admin_url)
    name = f"di1_test_{uuid.uuid4().hex[:12]}"
    statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        statement = sql.SQL("{} TEMPLATE {}").format(statement, sql.Identifier(template))
    _execute(admin_url, statement)
    try:
        yield _url_of(admin_url, name)
    finally:
        _drop(admin_url, name)


def fresh_database_url() -> Iterator[str]:
    """Create a uniquely named empty database, yield its SQLAlchemy URL, then drop it."""
    yield from _database(None)


def migrated_database_url() -> Iterator[str]:
    """Like `fresh_database_url`, but the database is already migrated to head."""
    yield from _database("migrated")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _drop_stale_templates(admin_url: str) -> None:
    """Drop the templates a killed test session left behind: their name carries the pid of the
    session that made them, and that process is gone. A live session's template is kept, and so
    is a template without a pid in its name (an older branch's naming: its owner cannot be told).
    The pid check is host-local: sessions on other hosts or in other PID namespaces must not share
    the test server, or their templates may be judged stale."""
    with psycopg.connect(psycopg_url(admin_url), autocommit=True) as admin:
        names = [
            row[0]
            for row in admin.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE 'di1\\_template\\_%'"
            )
        ]
    for name in names:
        parts = name.removeprefix("di1_template_").split("_")
        if len(parts) == 2 and parts[0].isdigit() and not _alive(int(parts[0])):
            _drop(admin_url, name)


def _migrated_template(admin_url: str) -> str:
    global _template
    if _template is None:
        _drop_stale_templates(admin_url)
        name = f"di1_template_{os.getpid()}_{uuid.uuid4().hex[:12]}"
        _execute(admin_url, sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            command.upgrade(alembic_config(_url_of(admin_url, name)), "head")
        except BaseException:
            _drop(admin_url, name)
            raise
        _template = name
    return _template


def drop_template() -> None:
    """Drop this session's migrated template, if one was made (``pytest_sessionfinish``)."""
    global _template
    if _template is not None:
        _drop(os.environ["TEST_DATABASE_URL"], _template)
        _template = None


# Seeding: the DI1 catalogue of `tests.support.builders`.

DI1_FUTURES = FuturesTerms(
    face_value=Decimal("100000"),
    contract_multiplier=Decimal("1"),
    settlement_method="CASH",
    settlement_description="Liquidação financeira",
)


def _connect(database: str | AsyncEngine) -> psycopg.Connection[tuple[Any, ...]]:
    """An autocommit libpq connection to a test database, given by URL or by its engine."""
    url = database if isinstance(database, str) else database.url.render_as_string(False)
    return psycopg.connect(psycopg_url(url), autocommit=True)


CATALOGUE_ROOTS_SQL = (
    "INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuros');"
    "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
    " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros');"
)
"""The instrument type FUTURE (id 1) and the asset class INTEREST_RATE_FUTURE (id 1), which have
no HTTP route (seeded data)."""


def catalogue_sql(contracts: Sequence[Instrument] = CATALOGUE) -> str:
    """SQL that seeds the catalogue roots, the DI1 product and ``contracts`` with their builder
    ids: the foreign-key targets of trades, prices and published rows. The asset tables are the
    same at every revision, so the migration tests seed with it too."""
    values = ", ".join(
        f"('{c.id}', '{PRODUCT_ID}', '{c.code}', '{c.maturity_date}')" for c in contracts
    )
    return (
        CATALOGUE_ROOTS_SQL + "INSERT INTO asset.products (id, asset_class_id, code, name)"
        f" VALUES ('{PRODUCT_ID}', 1, 'DI1', '{DI1_NAME}');"
        "INSERT INTO asset.futures (product_id, face_value, settlement_method)"
        f" VALUES ('{PRODUCT_ID}', 100000, 'CASH');"
        + (f"INSERT INTO asset.instruments (id, product_id, code, maturity_date) VALUES {values};")
    )


def seed_catalogue_roots(database: str | AsyncEngine) -> None:
    """`CATALOGUE_ROOTS_SQL` on a test database."""
    with _connect(database) as connection:
        connection.execute(CATALOGUE_ROOTS_SQL)


def seed_catalogue(
    database: str | AsyncEngine, contracts: Sequence[Instrument] = CATALOGUE
) -> None:
    """`catalogue_sql` on a test database."""
    with _connect(database) as connection:
        connection.execute(catalogue_sql(contracts))


@dataclass(frozen=True, slots=True)
class Di1Catalogue:
    future_type_id: int
    interest_rate_class_id: int
    di1_id: UUID
    instrument_ids: dict[str, UUID]


class Writer:
    """Runs one service write in its own Unit of Work, as one HTTP request would."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)

    async def instrument_type(self, code: str, name: str) -> int:
        async with self.uow() as uow:
            row = InstrumentTypeRow(code=code, name=name)
            uow.session.add(row)
            await uow.session.flush()
            type_id = row.id
            await uow.commit()
            return type_id

    async def asset_class(self, instrument_type_id: int, code: str, name: str) -> int:
        async with self.uow() as uow:
            row = AssetClassRow(instrument_type_id=instrument_type_id, code=code, name=name)
            uow.session.add(row)
            await uow.session.flush()
            class_id = row.id
            await uow.commit()
            return class_id

    async def product(
        self, asset_class_id: int, code: str, name: str, futures: FuturesTerms | None
    ) -> UUID:
        async with self.uow() as uow:
            created = await build_asset_service(uow).create_product(
                asset_class_id, code, name, futures
            )
            return created.id

    async def instrument(self, product_id: UUID, code: str, maturity: date | None) -> UUID:
        async with self.uow() as uow:
            created = await build_asset_service(uow).create_instrument(product_id, code, maturity)
            return created.id


async def seed_di1(session_factory: async_sessionmaker[AsyncSession]) -> Di1Catalogue:
    """FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27…DI1F30 of the catalogue, created through
    Asset's service (so their ids are generated)."""
    write = Writer(session_factory)
    future = await write.instrument_type("FUTURE", "Futuros")
    interest_rate = await write.asset_class(
        future, "INTEREST_RATE_FUTURE", "Futuros de Taxa de Juros"
    )
    di1 = await write.product(interest_rate, "DI1", DI1_NAME, DI1_FUTURES)
    contracts = {
        c.code: await write.instrument(di1, c.code, c.maturity_date)
        for c in (DI1F27, DI1F28, DI1F29, DI1F30)
    }
    return Di1Catalogue(future, interest_rate, di1, contracts)
