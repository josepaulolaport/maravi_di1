"""Registers every module's HTTP router on the app (integrator; interfaces.md "DI composition").

The module routes are served under ``/api`` (the frontend's ``API_BASE``, contract proposal P1);
``/health`` stays at the root. A router is a factory that takes the composition's providers,
because a module may not import ``composition``. Prices, Portfolio and Processing are added here
as they land.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from di1.composition.dependencies import get_ledger_service, get_unit_of_work
from di1.modules.asset.presentation.http.router import create_router as create_asset_router
from di1.modules.ledger.presentation.http.router import create_ledger_router

API_PREFIX = "/api"


def include_routers(app: FastAPI) -> None:
    """Include the module routers; ``main.create_app`` calls this once."""
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(create_asset_router(get_unit_of_work))
    api.include_router(
        create_ledger_router(get_service=get_ledger_service, get_unit_of_work=get_unit_of_work)
    )
    app.include_router(api)
