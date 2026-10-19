"""Asset HTTP: catalogue + last_reference from Prices (OQ-48)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, status

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.domain.model import Instrument
from di1.modules.asset.presentation.http.schemas import (
    CreateInstrumentIn,
    CreateProductIn,
    InstrumentList,
    InstrumentOut,
    InstrumentTypeList,
    InstrumentTypeOut,
    ProductList,
    ProductOut,
)
from di1.modules.prices.public import PriceReader, ReferencePriceRecord
from di1.platform.database.unit_of_work import UnitOfWork


def create_router(
    get_service: Callable[..., AssetService],
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
    prices: Callable[[UnitOfWork], PriceReader] | None = None,
) -> APIRouter:
    service_dependency = Depends(get_service)
    uow_dependency = Depends(get_unit_of_work)
    router = APIRouter(tags=["asset"])

    @router.get("/instrument-types")
    async def list_instrument_types(
        service: AssetService = service_dependency,
    ) -> InstrumentTypeList:
        types = await service.list_instrument_types()
        return InstrumentTypeList(items=[InstrumentTypeOut.of(t) for t in types])

    @router.get("/products")
    async def list_products(
        instrument_type: str | None = None,
        search: str | None = None,
        service: AssetService = service_dependency,
    ) -> ProductList:
        products = await service.list_products(instrument_type=instrument_type, search=search)
        return ProductList(items=[ProductOut.of(p) for p in products])

    @router.get("/products/{product_id}")
    async def get_product(
        product_id: UUID, service: AssetService = service_dependency
    ) -> ProductOut:
        return ProductOut.of(await service.get_product(product_id))

    @router.post("/products", status_code=status.HTTP_201_CREATED)
    async def create_product(
        body: CreateProductIn,
        service: AssetService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProductOut:
        return ProductOut.of(
            await service.create_product(
                body.asset_class_id,
                body.code,
                body.name,
                None if body.futures is None else body.futures.terms(),
                uow=uow,
            )
        )

    @router.get("/instruments")
    async def list_instruments(
        product_id: UUID | None = None,
        search: str | None = None,
        service: AssetService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> InstrumentList:
        instruments = await service.list_instruments(product_id=product_id, search=search)
        refs = await _latest_references(instruments, uow, prices)
        return InstrumentList(items=[InstrumentOut.of(i, refs.get(i.id)) for i in instruments])

    @router.get("/instruments/{instrument_id}")
    async def get_instrument(
        instrument_id: UUID,
        service: AssetService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> InstrumentOut:
        instrument = await service.get_instrument(instrument_id)
        refs = await _latest_references([instrument], uow, prices)
        return InstrumentOut.of(instrument, refs.get(instrument.id))

    @router.post("/instruments", status_code=status.HTTP_201_CREATED)
    async def create_instrument(
        body: CreateInstrumentIn,
        service: AssetService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> InstrumentOut:
        return InstrumentOut.of(
            await service.create_instrument(
                body.product_id, body.code, body.maturity_date, uow=uow
            ),
            None,
        )

    return router


async def _latest_references(
    instruments: Sequence[Instrument],
    uow: UnitOfWork,
    prices: Callable[[UnitOfWork], PriceReader] | None,
) -> Mapping[UUID, ReferencePriceRecord]:
    if prices is None or not instruments:
        return {}
    return await prices(uow).latest([i.id for i in instruments])
