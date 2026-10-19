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
from di1.modules.ledger.dependencies import create_ledger_service, ledger_reader
from di1.modules.portfolio.dependencies import portfolio_query_service
from di1.modules.portfolio.public import PortfolioQueryService
from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.dependencies import latest_price_reader, price_reader, price_service
from di1.modules.prices.public import LatestPriceReader
from di1.modules.pricing.dependencies import pricing_service
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.dependencies import make_date_status_reader, make_processing_service
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


def get_latest_prices(uow: UnitOfWork) -> LatestPriceReader:
    """Prices' latest preferred price per asset on ``uow``'s session, for Asset's
    ``Instrument.last_reference`` (OQ-48). Asset's router takes a plain factory of the Unit of
    Work."""
    return latest_price_reader(uow.session)


def build_price_service(uow: UnitOfWork, clock: Clock) -> PriceService:
    """Prices over Asset's reader and Pricing on ``uow``'s session. Prices' router takes a plain
    factory of the Unit of Work, so the composition binds the app's clock into it."""
    assets = asset_reader(uow.session)
    return price_service(uow, assets=assets, pricing=pricing_service(assets), clock=clock)


async def get_portfolio_query_service(
    uow: RequestUnitOfWork, clock: AppClock
) -> AsyncIterator[PortfolioQueryService]:
    """Portfolio's read models on the request's fresh Unit of Work. Nothing else runs on it
    first: the service's first statement opens the read-only REPEATABLE READ snapshot (OQ-23).
    Building the readers runs no statement."""
    yield portfolio_query_service(
        uow,
        assets=asset_reader(uow.session),
        prices=price_reader(uow.session),
        date_statuses=make_date_status_reader(),
        clock=clock,
    )


def get_processing_service(uow: RequestUnitOfWork, clock: AppClock) -> ProcessingService:
    """Processing over Asset's and Ledger's readers on the request's session; the service holds
    no state, so building it per request costs only the objects."""
    return make_processing_service(
        assets=asset_reader(uow.session), ledger=ledger_reader(uow.session), clock=clock
    )
