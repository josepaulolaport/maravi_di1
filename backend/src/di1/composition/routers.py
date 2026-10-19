"""Registers every module's HTTP router on the app (integrator; interfaces.md "DI composition").

The module routes are served under ``/api`` (the frontend's ``API_BASE``, contract proposal P1);
``/health`` stays at the root. A router is a factory that takes the composition's providers,
because a module may not import ``composition``.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from di1.composition.dependencies import (
    build_price_service,
    get_latest_prices,
    get_ledger_service,
    get_portfolio_query_service,
    get_processing_service,
    get_unit_of_work,
)
from di1.modules.asset.presentation.http.router import create_router as create_asset_router
from di1.modules.ledger.presentation.http.router import create_ledger_router
from di1.modules.portfolio.presentation.http.router import (
    create_router as create_portfolio_router,
)
from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.presentation.http.router import create_router as create_prices_router
from di1.modules.processing.presentation.http.router import (
    create_router as create_processing_router,
)
from di1.platform.database.unit_of_work import UnitOfWork

API_PREFIX = "/api"


def include_routers(app: FastAPI) -> None:
    """Include the module routers; ``main.create_app`` calls this once."""
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(create_asset_router(get_unit_of_work, get_latest_prices))
    api.include_router(
        create_ledger_router(get_service=get_ledger_service, get_unit_of_work=get_unit_of_work)
    )
    api.include_router(create_prices_router(get_unit_of_work, lambda uow: _price_service(app, uow)))
    api.include_router(create_portfolio_router(get_portfolio_query_service))
    api.include_router(create_processing_router(get_processing_service, get_unit_of_work))
    app.include_router(api)


def _price_service(app: FastAPI, uow: UnitOfWork) -> PriceService:
    # The clock is read when the request runs: ``create_app`` sets ``app.state.clock``.
    return build_price_service(uow, app.state.clock)
