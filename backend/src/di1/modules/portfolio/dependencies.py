"""Portfolio's module-local factories (interfaces.md "DI composition"). The composition root
calls them from its providers (HTTP) and plain factories (workers), passing the other modules'
readers it wires."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import AssetReader
from di1.modules.portfolio.application.services.previous_reader import PreviousDayReader
from di1.modules.portfolio.application.services.query_service import PortfolioQueries
from di1.modules.portfolio.application.services.results_writer import ResultsWriter
from di1.modules.portfolio.infrastructure.persistence.repositories import (
    SqlAlchemyPortfolioRepository,
)
from di1.modules.portfolio.public import (
    PortfolioQueryService,
    PortfolioReader,
    PortfolioResultsWriter,
)
from di1.modules.prices.public import PriceReader
from di1.modules.processing.public import DateStatusReader
from di1.platform.database.unit_of_work import UnitOfWork


def portfolio_repository(session: AsyncSession) -> SqlAlchemyPortfolioRepository:
    return SqlAlchemyPortfolioRepository(session)


def results_writer() -> PortfolioResultsWriter:
    """The writer; each call writes on the Unit of Work it is given (Processing's date)."""
    return ResultsWriter(lambda uow: SqlAlchemyPortfolioRepository(uow.session))


def portfolio_reader(session: AsyncSession) -> PortfolioReader:
    """`PortfolioReader` on the caller's session, so it reads inside the caller's transaction."""
    return PreviousDayReader(SqlAlchemyPortfolioRepository(session))


def portfolio_query_service(
    uow: UnitOfWork,
    *,
    assets: AssetReader,
    prices: PriceReader,
    date_statuses: DateStatusReader,
) -> PortfolioQueryService:
    """The read models on one fresh Unit of Work: its first statement makes the transaction one
    read-only REPEATABLE READ snapshot, in which the published rows and the date statuses are
    read (OQ-23). ``assets`` and ``prices`` should be built on the same session, and nothing may
    run on it before the service."""
    return PortfolioQueries(
        SqlAlchemyPortfolioRepository(uow.session),
        uow=uow,
        assets=assets,
        prices=prices,
        date_statuses=date_statuses,
    )
