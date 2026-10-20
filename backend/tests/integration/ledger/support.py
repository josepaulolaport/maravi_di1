"""Helpers for Ledger's PostgreSQL tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.platform.database.unit_of_work import UnitOfWork
from tests.support.builders import DI1F27, DI1F28, DI1F29, DI1V26

TODAY = date(2026, 10, 18)

CONTRACTS = (DI1F27, DI1F28, DI1F29, DI1V26)
"""The catalogue contracts Ledger's tests trade."""

ServiceOn = Callable[[UnitOfWork], LedgerService]
"""Builds the service on a Unit of Work, as the composition does per request."""


async def fetch(
    session_factory: async_sessionmaker[AsyncSession], sql: str, **params: Any
) -> Sequence[Row[Any]]:
    async with session_factory() as session:
        return (await session.execute(text(sql), params)).all()
