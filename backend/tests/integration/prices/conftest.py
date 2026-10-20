"""Fixtures for Prices' integration tests: the test's database with the catalogue contracts these
tests price, and a service on fake Asset and Pricing collaborators."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.dependencies import build_price_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.unit_of_work import UnitOfWork
from tests.integration.prices.support import CONTRACTS, TODAY, ServiceOn
from tests.support.db import seed_catalogue
from tests.support.fakes import FakeAssetReader, FakeClock, FakePricing


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    seed_catalogue(migrated_database_url, CONTRACTS)
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def assets() -> FakeAssetReader:
    fake = FakeAssetReader()
    for contract in CONTRACTS:
        fake.add(contract)
    return fake


@pytest.fixture
def service(assets: FakeAssetReader) -> ServiceOn:
    def on(uow: UnitOfWork) -> PriceService:
        return build_price_service(
            uow, assets=assets, pricing=FakePricing(), clock=FakeClock(TODAY)
        )

    return on
