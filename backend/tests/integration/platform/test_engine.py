"""The async engine reaches PostgreSQL 16 and keeps `NUMERIC` values exact as `Decimal`.

Plan §3 (Wave 0: async engine and session); CLAUDE.md §2 (34-digit `Decimal`, never float;
OQ-3); schema.sql (`TIMESTAMPTZ`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def test_engine_connects_to_postgresql_16(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        version = await connection.scalar(text("SHOW server_version_num"))

    assert version is not None and int(version) // 10000 == 16


async def test_numeric_round_trips_34_digits_exactly(engine: AsyncEngine) -> None:
    value = Decimal("98765.4321098765432109876543210987654")

    async with engine.connect() as connection:
        returned = await connection.scalar(text("SELECT CAST(:v AS NUMERIC)"), {"v": value})

    assert isinstance(returned, Decimal)
    assert returned == value


async def test_timestamptz_is_returned_aware(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        returned = await connection.scalar(text("SELECT now()"))

    assert isinstance(returned, datetime)
    assert returned.tzinfo is not None


async def test_session_factory_keeps_loaded_values_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert session_factory.kw["expire_on_commit"] is False
    assert session_factory.kw["autoflush"] is True
