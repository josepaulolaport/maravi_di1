"""Asset HTTP routes (interfaces.md "HTTP endpoints"; frontend contract ``api/contract/asset.ts``).

- ``GET /instrument-types``: each type with its asset classes (the catalogue tabs);
- ``GET /products?instrument_type=<code>&search=``, ``GET /products/{id}``, ``POST /products``
  → 201 (in interfaces.md; the current UI does not use it);
- ``GET /instruments?product_id=&search=`` (by maturity), ``GET /instruments/{id}``,
  ``POST /instruments`` → 201.

The composition root builds the router with its provider of the request's Unit of Work and a
factory of Prices' `LatestPriceReader` on that Unit of Work, which fills
``Instrument.last_reference`` (OQ-48); without the factory every ``last_reference`` is ``null``.
The service is built on the same Unit of Work, so a write commits the transaction it wrote in.
Errors are `DomainError`s raised by the service; this module raises none.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, status

from di1.modules.asset.application.services.asset_service import (
    AssetService,
    NewInstrument,
    NewProduct,
)
from di1.modules.asset.dependencies import asset_service
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
from di1.modules.prices.public import LatestPriceReader
from di1.platform.database.unit_of_work import UnitOfWork


def create_router(
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
    latest_prices: Callable[[UnitOfWork], LatestPriceReader] | None = None,
) -> APIRouter:
    """The Asset routes, each on the Unit of Work that ``get_unit_of_work`` provides."""

    def service(uow: UnitOfWork) -> AssetService:
        return asset_service(uow, None if latest_prices is None else latest_prices(uow))

    # A plain default, not ``Annotated``: with postponed annotations FastAPI resolves an
    # annotation in the module's globals, where this closure's provider is not.
    uow_dependency = Depends(get_unit_of_work)
    router = APIRouter(tags=["asset"])

    @router.get("/instrument-types")
    async def list_instrument_types(uow: UnitOfWork = uow_dependency) -> InstrumentTypeList:
        types = await service(uow).list_instrument_types()
        return InstrumentTypeList(items=[InstrumentTypeOut.of(t) for t in types])

    @router.get("/products")
    async def list_products(
        instrument_type: str | None = None,
        search: str | None = None,
        uow: UnitOfWork = uow_dependency,
    ) -> ProductList:
        products = await service(uow).list_products(instrument_type=instrument_type, search=search)
        return ProductList(items=[ProductOut.of(p) for p in products])

    @router.get("/products/{product_id}")
    async def get_product(product_id: UUID, uow: UnitOfWork = uow_dependency) -> ProductOut:
        return ProductOut.of(await service(uow).get_product(product_id))

    @router.post("/products", status_code=status.HTTP_201_CREATED)
    async def create_product(body: CreateProductIn, uow: UnitOfWork = uow_dependency) -> ProductOut:
        request = NewProduct(
            asset_class_id=body.asset_class_id,
            code=body.code,
            name=body.name,
            futures=None if body.futures is None else body.futures.terms(),
        )
        return ProductOut.of(await service(uow).create_product(request, uow=uow))

    @router.get("/instruments")
    async def list_instruments(
        product_id: UUID | None = None,
        search: str | None = None,
        uow: UnitOfWork = uow_dependency,
    ) -> InstrumentList:
        assets = service(uow)
        instruments = await assets.list_instruments(product_id=product_id, search=search)
        references = await assets.last_references(instruments)
        return InstrumentList(
            items=[InstrumentOut.of(i, references.get(i.id)) for i in instruments]
        )

    @router.get("/instruments/{instrument_id}")
    async def get_instrument(
        instrument_id: UUID, uow: UnitOfWork = uow_dependency
    ) -> InstrumentOut:
        assets = service(uow)
        instrument = await assets.get_instrument(instrument_id)
        references = await assets.last_references([instrument])
        return InstrumentOut.of(instrument, references.get(instrument.id))

    @router.post("/instruments", status_code=status.HTTP_201_CREATED)
    async def create_instrument(
        body: CreateInstrumentIn, uow: UnitOfWork = uow_dependency
    ) -> InstrumentOut:
        request = NewInstrument(
            product_id=body.product_id, code=body.code, maturity_date=body.maturity_date
        )
        # A contract created now has no price yet (prices reference an existing instrument).
        return InstrumentOut.of(await service(uow).create_instrument(request, uow=uow), None)

    return router
