"""Fixtures for Ledger's PostgreSQL tests: a fresh database migrated to head per test, the
fixtures' DI1 contracts in ``asset.*`` (the foreign key target of a trade), and a service wired
to the real repository with fake Asset/Pricing collaborators."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import create_ledger_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.shared.clock import FixedClock
from tests.fakes.processing import RecordingInvalidator
from tests.integration.databases import fresh_database_url
from tests.integration.ledger.support import TODAY, seed_contracts
from tests.unit.ledger.fakes import CalculatorPricer, FakeAssets

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
        async with engine.begin() as connection:
            await seed_contracts(connection)
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def invalidator() -> RecordingInvalidator:
    return RecordingInvalidator()


@pytest.fixture
def service(invalidator: RecordingInvalidator) -> LedgerService:
    assets = FakeAssets()
    return create_ledger_service(
        clock=FixedClock(TODAY),
        assets=assets,
        pricer=CalculatorPricer(assets),
        invalidator=invalidator,
    )
