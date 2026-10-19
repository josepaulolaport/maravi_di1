"""Fixtures for Processing's PostgreSQL tests: a fresh database per test, migrated to head."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from tests.integration.databases import fresh_database_url

BACKEND = Path(__file__).resolve().parents[3]


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from fresh_database_url()


@pytest.fixture
def migrated_database_url(database_url: str) -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)
