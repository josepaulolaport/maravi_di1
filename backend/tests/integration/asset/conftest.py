"""Fixtures for the Asset integration tests: a fresh, migrated PostgreSQL database per test, and the
DI1 catalogue of the frontend fixtures (``frontend/src/api/mocks/fixtures.ts``)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.dependencies import asset_service
from di1.modules.asset.domain.model import FuturesTerms
from di1.modules.asset.infrastructure.persistence.models import AssetClassRow, InstrumentTypeRow
from di1.modules.asset.infrastructure.persistence.repositories import SqlAssetRepository
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from tests.integration.databases import fresh_database_url

BACKEND = Path(__file__).resolve().parents[3]

DI1_NAME = "Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia"
DI1_FUTURES = FuturesTerms(
    face_value=Decimal("100000"),
    contract_multiplier=Decimal("1"),
    settlement_method="CASH",
    settlement_description="Liquidação financeira",
)
DI1_CONTRACTS = (
    ("DI1F27", date(2027, 1, 4)),
    ("DI1F28", date(2028, 1, 3)),
    ("DI1F29", date(2029, 1, 2)),
    ("DI1F30", date(2030, 1, 2)),
)


@dataclass(frozen=True, slots=True)
class Di1Catalogue:
    future_type_id: int
    interest_rate_class_id: int
    di1_id: UUID
    instrument_ids: dict[str, UUID]


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
            created = await asset_service(uow).create_product(
                asset_class_id, code, name, futures, uow=uow
            )
            return created.id

    async def instrument(self, product_id: UUID, code: str, maturity: date | None) -> UUID:
        async with self.uow() as uow:
            created = await asset_service(uow).create_instrument(
                product_id, code, maturity, uow=uow
            )
            return created.id


async def seed_di1(session_factory: async_sessionmaker[AsyncSession]) -> Di1Catalogue:
    """FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27…DI1F30, as in the frontend fixtures."""
    write = Writer(session_factory)
    future = await write.instrument_type("FUTURE", "Futuros")
    interest_rate = await write.asset_class(
        future, "INTEREST_RATE_FUTURE", "Futuros de Taxa de Juros"
    )
    di1 = await write.product(interest_rate, "DI1", DI1_NAME, DI1_FUTURES)
    contracts = {code: await write.instrument(di1, code, m) for code, m in DI1_CONTRACTS}
    return Di1Catalogue(future, interest_rate, di1, contracts)


@pytest.fixture
def writer(session_factory: async_sessionmaker[AsyncSession]) -> Writer:
    return Writer(session_factory)


@pytest.fixture
async def di1(session_factory: async_sessionmaker[AsyncSession]) -> Di1Catalogue:
    return await seed_di1(session_factory)


@pytest.fixture
async def reader_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def service(reader_session: AsyncSession) -> AssetService:
    """A read-only service on its own session."""
    return AssetService(SqlAssetRepository(reader_session))
