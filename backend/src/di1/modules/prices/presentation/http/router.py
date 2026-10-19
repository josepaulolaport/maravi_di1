"""``/reference-prices``: parse, call `PriceService`, shape the JSON."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.presentation.http.schemas import (
    ReferencePriceDayList,
    ReferencePriceDayResponse,
    ReferencePriceResponse,
    SetReferencePriceBody,
)
from di1.platform.database.unit_of_work import UnitOfWork


def create_router(
    get_service: Callable[..., PriceService],
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
) -> APIRouter:
    service_dependency = Depends(get_service)
    uow_dependency = Depends(get_unit_of_work)
    router = APIRouter(prefix="/reference-prices", tags=["prices"])

    @router.get("")
    async def list_reference_prices(
        asset_id: UUID,
        start_date: date,
        end_date: date,
        service: PriceService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ReferencePriceDayList:
        days = await service.list_reference_days(asset_id, start_date, end_date, uow=uow)
        return ReferencePriceDayList(items=[ReferencePriceDayResponse.of(day) for day in days])

    @router.post("", status_code=HTTPStatus.CREATED)
    async def set_reference_price(
        body: SetReferencePriceBody,
        service: PriceService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ReferencePriceResponse:
        record = await service.set_reference_price(
            body.asset_id,
            body.reference_date,
            body.input_kind,
            None if body.pu is None else Decimal(body.pu),
            None if body.rate is None else Decimal(body.rate),
            uow=uow,
        )
        return ReferencePriceResponse.of(record)

    @router.delete("/{price_id}", status_code=HTTPStatus.NO_CONTENT)
    async def remove_reference_price(
        price_id: UUID,
        service: PriceService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> Response:
        await service.remove_reference_price(price_id, uow=uow)
        return Response(status_code=HTTPStatus.NO_CONTENT)

    return router
