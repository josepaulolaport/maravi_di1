"""The async engine reaches PostgreSQL 16 and keeps `NUMERIC` values exact as `Decimal`.

Plan §3 (Wave 0: async engine and session); CLAUDE.md §2 (34-digit `Decimal`, never float;
OQ-3); schema.sql (`TIMESTAMPTZ`). The workers' startup check (`check_connection`) gives up on
a database that never answers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.engine import check_connection, create_engine


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


@pytest.fixture
async def hanging_database_settings() -> AsyncIterator[Settings]:
    """A TCP server that accepts connections and never answers: a database that hangs."""

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield Settings(
            database_url=SecretStr(f"postgresql+psycopg://u:s3cret-pw@127.0.0.1:{port}/db")
        )
    finally:
        server.close()


async def test_the_startup_check_gives_up_on_a_database_that_never_answers(
    hanging_database_settings: Settings,
) -> None:
    """Without a stop, a database that hangs must still end the process (exit 1), so the
    restart policy applies."""
    engine = create_engine(hanging_database_settings)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check_connection(engine, timeout_seconds=0.3), timeout=5)
    finally:
        await engine.dispose()
