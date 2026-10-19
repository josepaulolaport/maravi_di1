"""``/reference-prices`` (interfaces.md "HTTP endpoints"; frontend contract ``prices.ts``;
OQ-25, OQ-26 items 7 and 8). Parse, call `PriceService`, shape the answer; no rules here.

The composition root builds the router with its provider of the request's Unit of Work and a
factory of the service on that Unit of Work (``dependencies.price_service`` with the other
modules' collaborators), so a write commits the transaction it wrote in. Errors are
`DomainError`s raised by the service; this module raises none.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from di1.modules.prices.application.services.price_service import PriceService, SetReferencePrice
from di1.modules.prices.presentation.http.schemas import (
    ReferencePriceDayList,
    ReferencePriceDayResponse,
    ReferencePriceResponse,
    SetReferencePriceBody,
)
from di1.modules.prices.public import PriceSource
from di1.platform.database.unit_of_work import UnitOfWork


def create_router(
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
    price_service: Callable[[UnitOfWork], PriceService],
) -> APIRouter:
    """The Prices routes, each on the Unit of Work that ``get_unit_of_work`` provides."""
    # A plain default, not ``Annotated``: with postponed annotations FastAPI resolves an
    # annotation in the module's globals, where this closure's provider is not.
    uow_dependency = Depends(get_unit_of_work)
    router = APIRouter(prefix="/reference-prices", tags=["prices"])

    @router.get("")
    async def list_reference_prices(
        asset_id: UUID,
        start_date: date,
        end_date: date,
        uow: UnitOfWork = uow_dependency,
    ) -> ReferencePriceDayList:
        days = await price_service(uow).list_reference_days(asset_id, start_date, end_date, uow=uow)
        return ReferencePriceDayList(items=[ReferencePriceDayResponse.of(day) for day in days])

    @router.post("", status_code=HTTPStatus.CREATED)
    async def set_reference_price(
        body: SetReferencePriceBody, uow: UnitOfWork = uow_dependency
    ) -> ReferencePriceResponse:
        record = await price_service(uow).set_reference_price(
            SetReferencePrice(
                asset_id=body.asset_id,
                reference_date=body.reference_date,
                input_kind=body.input_kind,
                pu=None if body.pu is None else Decimal(body.pu),
                rate=None if body.rate is None else Decimal(body.rate),
                source=PriceSource.MANUAL,
            ),
            uow=uow,
        )
        return ReferencePriceResponse.of(record)

    @router.delete("/{price_id}", status_code=HTTPStatus.NO_CONTENT)
    async def remove_reference_price(price_id: UUID, uow: UnitOfWork = uow_dependency) -> Response:
        await price_service(uow).remove_reference_price(price_id, uow=uow)
        return Response(status_code=HTTPStatus.NO_CONTENT)

    return router
