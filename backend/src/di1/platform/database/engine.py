"""The async SQLAlchemy engine on PostgreSQL through psycopg 3 (plan §3, Wave 0).

One engine per process: the API and each worker create it at startup and dispose of it at
shutdown.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from di1.platform.config import Settings


def create_engine(settings: Settings, *, server_options: str | None = None) -> AsyncEngine:
    """``server_options`` is libpq's ``options``, run-time parameters set on every connection
    (``-c name=value ...``)."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        echo=settings.database_echo,
        connect_args={} if server_options is None else {"options": server_options},
    )


def create_worker_engine(settings: Settings) -> AsyncEngine:
    """The processing worker's engine: every connection has ``statement_timeout`` and
    ``lock_timeout`` set, so a hung query or lock wait raises (an `OperationalError`, which the
    processor treats as transient) instead of hanging the worker forever."""
    statement_ms = round(settings.worker_statement_timeout_seconds * 1000)
    lock_ms = round(settings.worker_lock_timeout_seconds * 1000)
    return create_engine(
        settings,
        server_options=f"-c statement_timeout={statement_ms} -c lock_timeout={lock_ms}",
    )


async def check_connection(engine: AsyncEngine, *, timeout_seconds: float = 5.0) -> None:
    """Raise unless PostgreSQL answers ``SELECT 1`` within ``timeout_seconds`` (`TimeoutError`
    then): a worker fails at startup, not on its first unit of work, when the database is
    unreachable, misconfigured or hangs."""
    async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
