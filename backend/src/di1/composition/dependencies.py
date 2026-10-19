"""Cross-module dependency providers for the HTTP adapters (integrator; interfaces.md
"DI composition").

A request that writes opens one Unit of Work over the app's session factory; the service commits
it once. FastAPI caches a dependency per request, so every provider below that depends on
`get_unit_of_work` receives the same Unit of Work as the route: a service and the readers of other
modules it uses all work in the request's one transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import asset_reader
from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import create_ledger_service
from di1.modules.pricing.dependencies import pricing_service
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.clock import Clock


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The session factory the lifespan created for this process."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_unit_of_work(request: Request) -> AsyncIterator[UnitOfWork]:
    """One Unit of Work for the request; it rolls back unless the service committed it."""
    async with SqlAlchemyUnitOfWork(get_session_factory(request)) as uow:
        yield uow


def get_clock(request: Request) -> Clock:
    """The app's clock (OQ-14): `SystemClock` in production, a `FixedClock` in tests."""
    clock: Clock = request.app.state.clock
    return clock


RequestUnitOfWork = Annotated[UnitOfWork, Depends(get_unit_of_work)]
AppClock = Annotated[Clock, Depends(get_clock)]


def get_ledger_service(uow: RequestUnitOfWork, clock: AppClock) -> LedgerService:
    """Ledger over Asset's reader and Pricing, both on the request's session."""
    assets = asset_reader(uow.session)
    return create_ledger_service(clock=clock, assets=assets, pricing=pricing_service(assets))
