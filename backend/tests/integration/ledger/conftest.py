"""Fixtures for Ledger's PostgreSQL tests: a fresh database migrated to head per test, the
fixtures' DI1 contracts in ``asset.*`` (the foreign key target of a trade), and a service wired
to the real repository with fake Asset/Pricing collaborators."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import build_ledger_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.unit_of_work import UnitOfWork
from tests.fakes.clock import FixedClock
from tests.integration.ledger.support import TODAY, seed_contracts
from tests.unit.ledger.fakes import FakeAssets, FormulaPricing


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        async with engine.begin() as connection:
            await seed_contracts(connection)
        yield engine
    finally:
        await engine.dispose()


ServiceOn = Callable[[UnitOfWork], LedgerService]
"""Builds the service on a Unit of Work, as the composition does per request."""


@pytest.fixture
def service() -> ServiceOn:
    assets = FakeAssets()

    def on(uow: UnitOfWork) -> LedgerService:
        return build_ledger_service(
            uow, clock=FixedClock(TODAY), assets=assets, pricing=FormulaPricing(assets)
        )

    return on
