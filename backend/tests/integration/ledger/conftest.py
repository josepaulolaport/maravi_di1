"""Fixtures for Ledger's PostgreSQL tests: the test's database with the catalogue's DI1 contracts
in ``asset.*`` (the foreign key target of a trade), and a service wired
to the real repository and the real pricing over a fake Asset reader."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import build_ledger_service
from di1.modules.pricing.dependencies import build_pricing_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.unit_of_work import UnitOfWork
from tests.integration.ledger.support import CONTRACTS, TODAY, ServiceOn
from tests.support.db import seed_catalogue
from tests.support.fakes import FakeAssetReader, FakeClock


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
    assets = FakeAssetReader(*CONTRACTS)

    def on(uow: UnitOfWork) -> LedgerService:
        return build_ledger_service(
            uow, clock=FakeClock(TODAY), assets=assets, pricing=build_pricing_service(assets)
        )

    return on
