"""Fixtures for Prices' integration tests: a fresh, migrated PostgreSQL database per test, with
the instruments of the frontend's demo fixtures (``frontend/src/api/mocks/fixtures.ts``)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.asset.public import InstrumentDescriptor
from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.infrastructure.persistence.repositories import (
    SqlReferencePriceRepository,
)
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.shared.clock import FixedClock
from tests.integration.databases import fresh_database_url
from tests.unit.prices.fakes import FakeAssets, FakePricing

BACKEND = Path(__file__).resolve().parents[3]
TODAY = date(2026, 10, 19)

PRODUCT = UUID("6f1c2a10-0000-4000-8000-000000000001")
DI1F28 = UUID("6f1c2a10-0000-4000-8000-0000000000f8")
DI1F29 = UUID("6f1c2a10-0000-4000-8000-0000000000f9")
MATURED = UUID("6f1c2a10-0000-4000-8000-0000000000aa")
INSTRUMENTS = {
    DI1F28: ("DI1F28", date(2028, 1, 3)),
    DI1F29: ("DI1F29", date(2029, 1, 2)),
    MATURED: ("DI1V26", date(2026, 10, 1)),
}


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
        await _seed_instruments(engine)
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def assets() -> FakeAssets:
    fake = FakeAssets()
    for instrument_id, (code, maturity) in INSTRUMENTS.items():
        fake.add(
            InstrumentDescriptor(
                id=instrument_id,
                code=code,
                product_id=PRODUCT,
                product_code="DI1",
                instrument_type="FUTURE",
                asset_class="INTEREST_RATE_FUTURE",
                maturity_date=maturity,
                face_value=Decimal("100000"),
                multiplier=Decimal("1"),
                settlement_method="CASH",
            )
        )
    return fake


@pytest.fixture
def service(assets: FakeAssets) -> PriceService:
    return PriceService(
        assets=assets,
        pricing=FakePricing(),
        repositories=SqlReferencePriceRepository.of,
        clock=FixedClock(TODAY),
    )


async def _seed_instruments(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO asset.instrument_types (id, code, name)"
                " VALUES (1, 'FUTURE', 'Futuros')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
                " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de juros')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO asset.products (id, asset_class_id, code, name)"
                " VALUES (:id, 1, 'DI1', 'DI1')"
            ),
            {"id": PRODUCT},
        )
        await connection.execute(
            text(
                "INSERT INTO asset.instruments (id, product_id, code, maturity_date)"
                " VALUES (:id, :product, :code, :maturity)"
            ),
            [
                {"id": i, "product": PRODUCT, "code": code, "maturity": maturity}
                for i, (code, maturity) in INSTRUMENTS.items()
            ],
        )
