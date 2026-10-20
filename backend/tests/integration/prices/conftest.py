"""Fixtures for Prices' integration tests: the test's database with the catalogue contracts these
tests price, and a service on the real Asset reader and Pricing service."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.dependencies import build_price_service
from di1.modules.pricing.dependencies import build_pricing_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.unit_of_work import UnitOfWork
from tests.integration.prices.support import CONTRACTS, TODAY, ServiceOn
from tests.support.db import seed_catalogue
from tests.support.fakes import FakeClock


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    seed_catalogue(migrated_database_url, CONTRACTS)
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def service() -> ServiceOn:
    """The service with the real Asset reader and Pricing service on the caller's session, as
    the composition wires it."""

    def on(uow: UnitOfWork) -> PriceService:
        assets = build_asset_reader(uow.session)
        return build_price_service(
            uow, assets=assets, pricing=build_pricing_service(assets), clock=FakeClock(TODAY)
        )

    return on
