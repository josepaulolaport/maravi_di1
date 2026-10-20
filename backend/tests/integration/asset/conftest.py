"""Fixtures for the Asset integration tests: a read-only service and session on the test's database
(`tests/integration/conftest.py`)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.dependencies import build_asset_service
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
async def reader_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def service(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AssetService]:
    """A service on its own Unit of Work, used for reads only."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield build_asset_service(uow)
