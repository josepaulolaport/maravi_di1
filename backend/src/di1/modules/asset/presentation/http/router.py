"""Asset HTTP: the catalogue, each instrument with its ``last_reference`` from Prices (OQ-48)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, status

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.domain.model import Instrument
from di1.modules.asset.presentation.http.schemas import (
    CreateInstrumentRequest,
    CreateProductRequest,
    InstrumentListResponse,
    InstrumentResponse,
    InstrumentTypeListResponse,
    InstrumentTypeResponse,
    ProductListResponse,
    ProductResponse,
)
from di1.modules.prices.public import PriceReader, ReferencePriceRecord


def create_router(
    *,
    get_service: Callable[..., AssetService],
    get_price_reader: Callable[..., PriceReader],
) -> APIRouter:
    # Dependency objects built here: the handlers' annotations are strings (PEP 563), resolved
    # from the module's globals, so they cannot name a local alias.
    service_dependency = Depends(get_service)
    prices_dependency = Depends(get_price_reader)
    router = APIRouter(tags=["asset"])

    @router.get("/instrument-types")
    async def list_instrument_types(
        service: AssetService = service_dependency,
    ) -> InstrumentTypeListResponse:
        types = await service.list_instrument_types()
        return InstrumentTypeListResponse(items=[InstrumentTypeResponse.of(t) for t in types])

    @router.get("/products")
    async def list_products(
        instrument_type: str | None = None,
        search: str | None = None,
        service: AssetService = service_dependency,
    ) -> ProductListResponse:
        products = await service.list_products(instrument_type=instrument_type, search=search)
        return ProductListResponse(items=[ProductResponse.of(p) for p in products])

    @router.get("/products/{product_id}")
    async def get_product(
        product_id: UUID, service: AssetService = service_dependency
    ) -> ProductResponse:
        return ProductResponse.of(await service.get_product(product_id))

    @router.post("/products", status_code=status.HTTP_201_CREATED)
    async def create_product(
        body: CreateProductRequest, service: AssetService = service_dependency
    ) -> ProductResponse:
        futures = None if body.futures is None else body.futures.terms()
        product = await service.create_product(body.asset_class_id, body.code, body.name, futures)
        return ProductResponse.of(product)

    @router.get("/instruments")
    async def list_instruments(
        product_id: UUID | None = None,
        search: str | None = None,
        service: AssetService = service_dependency,
        prices: PriceReader = prices_dependency,
    ) -> InstrumentListResponse:
        instruments = await service.list_instruments(product_id=product_id, search=search)
        refs = await _latest_references(instruments, prices)
        return InstrumentListResponse(
            items=[InstrumentResponse.of(i, refs.get(i.id)) for i in instruments]
        )

    @router.get("/instruments/{instrument_id}")
    async def get_instrument(
        instrument_id: UUID,
        service: AssetService = service_dependency,
        prices: PriceReader = prices_dependency,
    ) -> InstrumentResponse:
        instrument = await service.get_instrument(instrument_id)
        refs = await _latest_references([instrument], prices)
        return InstrumentResponse.of(instrument, refs.get(instrument.id))

    @router.post("/instruments", status_code=status.HTTP_201_CREATED)
    async def create_instrument(
        body: CreateInstrumentRequest, service: AssetService = service_dependency
    ) -> InstrumentResponse:
        instrument = await service.create_instrument(body.product_id, body.code, body.maturity_date)
        return InstrumentResponse.of(instrument, None)

    return router


async def _latest_references(
    instruments: Sequence[Instrument], prices: PriceReader
) -> Mapping[UUID, ReferencePriceRecord]:
    if not instruments:
        return {}
    return await prices.latest([i.id for i in instruments])
