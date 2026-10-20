"""The async engine reaches PostgreSQL 16 and keeps `NUMERIC` values exact as `Decimal`.

Plan §3 (Wave 0: async engine and session); CLAUDE.md §2 (34-digit `Decimal`, never float;
OQ-3); schema.sql (`TIMESTAMPTZ`). The workers' startup check (`check_connection`) gives up on
a database that never answers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import Settings
from di1.platform.database.engine import check_connection, create_engine, create_worker_engine


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


async def test_the_api_engine_keeps_the_server_default_timeouts(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        statement = await connection.scalar(text("SHOW statement_timeout"))
        lock = await connection.scalar(text("SHOW lock_timeout"))

    assert (statement, lock) == ("0", "0")


async def test_the_worker_engine_sets_statement_and_lock_timeouts(settings: Settings) -> None:
    engine = create_worker_engine(settings)
    try:
        async with engine.connect() as connection:
            statement = await connection.scalar(text("SHOW statement_timeout"))
            lock = await connection.scalar(text("SHOW lock_timeout"))
    finally:
        await engine.dispose()

    assert (statement, lock) == ("1min", "10s")


async def test_a_worker_lock_wait_ends_with_an_operational_error(
    settings: Settings, engine: AsyncEngine
) -> None:
    """A lock held elsewhere no longer hangs the worker: its wait ends after the lock timeout
    with an operational error, which the processor treats as transient."""
    worker_engine = create_worker_engine(
        settings.model_copy(update={"worker_lock_timeout_seconds": 0.2})
    )
    try:
        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_lock(42)"))
            async with worker_engine.connect() as waiter:
                with pytest.raises(OperationalError, match="lock timeout"):
                    await asyncio.wait_for(
                        waiter.execute(text("SELECT pg_advisory_lock(42)")), timeout=5
                    )
            await holder.execute(text("SELECT pg_advisory_unlock(42)"))
    finally:
        await worker_engine.dispose()


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
