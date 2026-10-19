"""Cross-module dependency providers for the HTTP adapters (integrator; interfaces.md
"DI composition").

A request that writes opens one Unit of Work over the app's session factory; the service commits
it once. Module providers that need collaborators from other modules are wired here as they land.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The session factory the lifespan created for this process."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_unit_of_work(request: Request) -> AsyncIterator[UnitOfWork]:
    """One Unit of Work for the request; it rolls back unless the service committed it."""
    async with SqlAlchemyUnitOfWork(get_session_factory(request)) as uow:
        yield uow
