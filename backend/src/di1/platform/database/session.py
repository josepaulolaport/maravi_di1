"""The `AsyncSession` factory.

``expire_on_commit=False``: a service can still read what it saved after the commit (to build
its response DTO) without a new query, which an async session could not issue implicitly.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=True)
