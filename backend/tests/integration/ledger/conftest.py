"""Fixtures for Ledger's PostgreSQL tests: the test's database with the catalogue's DI1 contracts
in ``asset.*`` (the foreign key target of a trade), and a service wired
to the real repository with fake Asset/Pricing collaborators."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import build_ledger_service
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.unit_of_work import UnitOfWork
from tests.fakes.clock import FixedClock
from tests.integration.ledger.support import TODAY, ServiceOn
from tests.support.builders import DI1F27, DI1F28, DI1F29, DI1V26
from tests.support.db import seed_catalogue
from tests.unit.ledger.fakes import FakeAssets, FormulaPricing


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    seed_catalogue(migrated_database_url, (DI1F27, DI1F28, DI1F29, DI1V26))
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def service() -> ServiceOn:
    assets = FakeAssets()

    def on(uow: UnitOfWork) -> LedgerService:
        return build_ledger_service(
            uow, clock=FixedClock(TODAY), assets=assets, pricing=FormulaPricing(assets)
        )

    return on
