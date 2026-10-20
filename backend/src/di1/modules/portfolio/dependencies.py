"""Portfolio's module-local factories (interfaces.md "DI composition"). The composition root
calls them from its providers (HTTP) and plain factories (workers), passing the other modules'
readers it wires, each built on the same session."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.portfolio.application.services.portfolio_reader import DefaultPortfolioReader
from di1.modules.portfolio.application.services.query_service import DefaultPortfolioService
from di1.modules.portfolio.application.services.results_writer import DefaultResultsWriter
from di1.modules.portfolio.infrastructure.persistence.repositories import (
    SqlPortfolioRepository,
)
from di1.modules.portfolio.public import (
    PortfolioReader,
    PortfolioResultsWriter,
    PortfolioService,
)
from di1.modules.prices.public import PriceReader
from di1.modules.processing.public import DateStatusReader
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def build_results_writer(session: AsyncSession) -> PortfolioResultsWriter:
    """The writer on Processing's date session: the rows land in that date's transaction."""
    return DefaultResultsWriter(SqlPortfolioRepository(session))


def build_portfolio_reader(session: AsyncSession) -> PortfolioReader:
    """`PortfolioReader` on the caller's session, so it reads inside the caller's transaction."""
    return DefaultPortfolioReader(SqlPortfolioRepository(session))


def build_portfolio_service(
    uow: UnitOfWork,
    *,
    assets: AssetReader,
    prices: PriceReader,
    date_statuses: DateStatusReader,
    clock: Clock,
) -> PortfolioService:
    """The read models on one fresh Unit of Work: its first statement makes the transaction one
    read-only REPEATABLE READ snapshot, in which the published rows and the date statuses are
    read (OQ-23). ``assets``, ``prices`` and ``date_statuses`` should be built on
    ``uow.session``, and nothing may run on it before the service. ``clock`` gives "today" in São
    Paulo: a read dated after it is refused with FUTURE_DATE (OQ-35)."""
    return DefaultPortfolioService(
        SqlPortfolioRepository(uow.session),
        assets=assets,
        prices=prices,
        date_statuses=date_statuses,
        clock=clock,
    )
