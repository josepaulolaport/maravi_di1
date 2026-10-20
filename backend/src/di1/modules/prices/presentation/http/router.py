"""``/reference-prices``: parse, call `PriceService`, shape the JSON."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, status

from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.presentation.http.schemas import (
    ReferencePriceDayListResponse,
    ReferencePriceDayResponse,
    ReferencePriceResponse,
    SetReferencePriceRequest,
)


def create_router(*, get_service: Callable[..., PriceService]) -> APIRouter:
    # Dependency objects built here: the handlers' annotations are strings (PEP 563), resolved
    # from the module's globals, so they cannot name a local alias.
    service_dependency = Depends(get_service)
    router = APIRouter(prefix="/reference-prices", tags=["prices"])

    @router.get("")
    async def list_reference_prices(
        asset_id: UUID,
        start_date: date,
        end_date: date,
        service: PriceService = service_dependency,
    ) -> ReferencePriceDayListResponse:
        days = await service.list_reference_days(asset_id, start_date, end_date)
        return ReferencePriceDayListResponse(
            items=[ReferencePriceDayResponse.of(day) for day in days]
        )

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def set_reference_price(
        body: SetReferencePriceRequest, service: PriceService = service_dependency
    ) -> ReferencePriceResponse:
        record = await service.set_reference_price(
            body.asset_id, body.reference_date, body.input_kind, body.pu, body.rate
        )
        return ReferencePriceResponse.of(record)

    @router.delete("/{price_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_reference_price(
        price_id: UUID, service: PriceService = service_dependency
    ) -> None:
        await service.remove_reference_price(price_id)

    return router
