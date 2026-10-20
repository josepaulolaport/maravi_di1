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


def alembic_config(database_url: str) -> Config:
    """The project's Alembic configuration, pointed at ``database_url``."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


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


def _migrated_template(admin_url: str) -> str:
    global _template
    if _template is None:
        name = f"di1_template_{uuid.uuid4().hex[:12]}"
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


def seed_catalogue_roots(database: str | AsyncEngine) -> None:
    """The instrument type FUTURE (id 1) and the asset class INTEREST_RATE_FUTURE (id 1), which have
    no HTTP route (seeded data)."""
    with _connect(database) as connection:
        connection.execute(
            "INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuros')"
        )
        connection.execute(
            "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
            " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros')"
        )


def seed_catalogue(
    database: str | AsyncEngine, contracts: Sequence[Instrument] = CATALOGUE
) -> None:
    """The catalogue roots, the DI1 product and ``contracts``, with their builder ids, in plain SQL:
    the foreign-key targets of trades, prices and published rows."""
    seed_catalogue_roots(database)
    with _connect(database) as connection:
        connection.execute(
            "INSERT INTO asset.products (id, asset_class_id, code, name) VALUES (%s, 1, 'DI1', %s)",
            (PRODUCT_ID, DI1_NAME),
        )
        connection.execute(
            "INSERT INTO asset.futures (product_id, face_value, settlement_method)"
            " VALUES (%s, 100000, 'CASH')",
            (PRODUCT_ID,),
        )
        for contract in contracts:
            connection.execute(
                "INSERT INTO asset.instruments (id, product_id, code, maturity_date)"
                " VALUES (%s, %s, %s, %s)",
                (contract.id, PRODUCT_ID, contract.code, contract.maturity_date),
            )


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
