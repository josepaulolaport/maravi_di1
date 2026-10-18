"""The async SQLAlchemy engine on PostgreSQL through psycopg 3 (plan §3, Wave 0).

One engine per process: the API and each worker create it at startup and dispose of it at
shutdown.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from di1.platform.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        echo=settings.database_echo,
    )
