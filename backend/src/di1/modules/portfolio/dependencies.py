"""Portfolio's module-local factories (interfaces.md "DI composition"). The composition root
calls them from its providers (HTTP) and plain factories (workers), passing the other modules'
readers it wires."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.portfolio.application.services.portfolio_reader import PortfolioReader
from di1.modules.portfolio.application.services.query_service import PortfolioService
from di1.modules.portfolio.application.services.results_writer import PortfolioResultsWriter
from di1.modules.portfolio.infrastructure.persistence.repositories import (
    SqlPortfolioRepository,
)
from di1.modules.portfolio.public import (
    PortfolioReader as PortfolioReaderPort,
)
from di1.modules.prices.public import PriceReader
from di1.modules.processing.public import DateStatusReader
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def results_writer() -> PortfolioResultsWriter:
    """The writer; each call writes on the Unit of Work it is given (Processing's date)."""
    return PortfolioResultsWriter(lambda uow: SqlPortfolioRepository(uow.session))


def portfolio_reader(session: AsyncSession) -> PortfolioReaderPort:
    """`PortfolioReader` on the caller's session, so it reads inside the caller's transaction."""
    return PortfolioReader(SqlPortfolioRepository(session))


def portfolio_query_service(
    uow: UnitOfWork,
    *,
    assets: AssetReader,
    prices: PriceReader,
    date_statuses: DateStatusReader,
    clock: Clock,
) -> PortfolioService:
    """The read models on one fresh Unit of Work: its first statement makes the transaction one
    read-only REPEATABLE READ snapshot, in which the published rows and the date statuses are
    read (OQ-23). ``assets`` and ``prices`` should be built on the same session, and nothing may
    run on it before the service. ``clock`` gives "today" in São Paulo: a read dated after it is
    refused with FUTURE_DATE (OQ-35)."""
    return PortfolioService(
        SqlPortfolioRepository(uow.session),
        uow=uow,
        assets=assets,
        prices=prices,
        date_statuses=date_statuses,
        clock=clock,
    )
