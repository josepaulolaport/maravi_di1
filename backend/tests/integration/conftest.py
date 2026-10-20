"""Fixtures every integration test shares: a database of its own, copied from the session's
migrated template (`tests.support.db`), and the engine and session factory on it. A module's
conftest overrides ``engine`` when its tests need seed rows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from tests.support import db
from tests.support.db import Di1Catalogue, Writer, seed_di1


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    yield from db.migrated_database_url()


@pytest.fixture
def settings(migrated_database_url: str) -> Settings:
    return Settings(database_url=SecretStr(migrated_database_url))


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def writer(session_factory: async_sessionmaker[AsyncSession]) -> Writer:
    return Writer(session_factory)


@pytest.fixture
async def di1(session_factory: async_sessionmaker[AsyncSession]) -> Di1Catalogue:
    return await seed_di1(session_factory)
