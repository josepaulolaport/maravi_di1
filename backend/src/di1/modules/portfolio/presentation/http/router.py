"""Portfolio HTTP routes (interfaces.md "HTTP endpoints"; frontend contract
``api/contract/portfolio.ts``):

- ``GET /portfolio/summary?date=YYYY-MM-DD``: both chains of the date and AUM;
- ``GET /portfolio/positions?date=YYYY-MM-DD``: the positions table of the date;
- ``GET /portfolio/pnl?start_date=&end_date=``: every date of the range, ``{items}`` (OQ-16,
  OQ-27, OQ-31 item 8, OQ-41).

Published data only, never recalculated on GET (spec §11.4). The composition root builds the
router with its provider of the query service, which wires Asset, Prices and Processing's
readers on the request's Unit of Work. A malformed date is answered 422 ``VALIDATION_ERROR`` by
the app's handlers; a start after the end is the service's ``INVALID_RANGE``, and a ``date`` or
``end_date`` after today its ``FUTURE_DATE`` (OQ-35).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date

from fastapi import APIRouter, Depends, Query

from di1.modules.portfolio.presentation.http.schemas import (
    PnlPointOut,
    PnlSeriesOut,
    PortfolioPositionsOut,
    PortfolioSummaryOut,
)
from di1.modules.portfolio.public import PortfolioService


def create_router(
    get_query_service: Callable[..., AsyncIterator[PortfolioService]],
) -> APIRouter:
    """The Portfolio routes, each on the query service that ``get_query_service`` provides."""
    # A plain default, not ``Annotated``: with postponed annotations FastAPI resolves an
    # annotation in the module's globals, where this closure's provider is not.
    service_dependency = Depends(get_query_service)
    date_query = Query(alias="date")  # ?date=YYYY-MM-DD; ``date`` would shadow the type
    router = APIRouter(prefix="/portfolio", tags=["portfolio"])

    @router.get("/summary")
    async def get_summary(
        on: date = date_query,
        service: PortfolioService = service_dependency,
    ) -> PortfolioSummaryOut:
        return PortfolioSummaryOut.of(await service.get_summary(on))

    @router.get("/positions")
    async def get_positions(
        on: date = date_query,
        service: PortfolioService = service_dependency,
    ) -> PortfolioPositionsOut:
        return PortfolioPositionsOut.of(await service.get_position_table(on))

    @router.get("/pnl")
    async def get_pnl(
        start_date: date,
        end_date: date,
        service: PortfolioService = service_dependency,
    ) -> PnlSeriesOut:
        points = await service.get_pnl_series(start_date, end_date)
        return PnlSeriesOut(items=[PnlPointOut.of(p) for p in points])

    return router
