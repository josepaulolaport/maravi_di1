"""HTTP shapes of the Asset routes: the frontend contract ``frontend/src/api/contract/asset.ts``
(OQ-26 item 8). Decimals cross as strings in plain notation; absent values are ``null``.
Schemas check syntax only; business rules are the service's."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from di1.modules.asset.domain.model import (
    AssetClass,
    FuturesTerms,
    Instrument,
    InstrumentType,
    Product,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.platform.http import DecimalString, RequestBody, UtcDatetime
from di1.shared.decimals import to_plain


class AssetClassResponse(BaseModel):
    id: int
    code: str
    name: str

    @classmethod
    def of(cls, asset_class: AssetClass) -> Self:
        return cls(id=asset_class.id, code=asset_class.code, name=asset_class.name)


class InstrumentTypeRefResponse(BaseModel):
    id: int
    code: str
    name: str

    @classmethod
    def of(cls, instrument_type: InstrumentType) -> Self:
        return cls(id=instrument_type.id, code=instrument_type.code, name=instrument_type.name)


class InstrumentTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    asset_classes: list[AssetClassResponse]

    @classmethod
    def of(cls, instrument_type: InstrumentType) -> Self:
        return cls(
            id=instrument_type.id,
            code=instrument_type.code,
            name=instrument_type.name,
            asset_classes=[AssetClassResponse.of(c) for c in instrument_type.asset_classes],
        )


class FuturesSpecResponse(BaseModel):
    face_value: str
    contract_multiplier: str
    settlement_method: str
    settlement_description: str | None

    @classmethod
    def of(cls, futures: FuturesTerms) -> Self:
        return cls(
            face_value=to_plain(futures.face_value),
            contract_multiplier=to_plain(futures.contract_multiplier),
            settlement_method=futures.settlement_method,
            settlement_description=futures.settlement_description,
        )


class ProductResponse(BaseModel):
    id: UUID
    code: str
    name: str
    asset_class: AssetClassResponse
    instrument_type: InstrumentTypeRefResponse
    instrument_count: int
    futures: FuturesSpecResponse | None
    created_at: UtcDatetime

    @classmethod
    def of(cls, product: Product) -> Self:
        return cls(
            id=product.id,
            code=product.code,
            name=product.name,
            asset_class=AssetClassResponse.of(product.asset_class),
            instrument_type=InstrumentTypeRefResponse.of(product.instrument_type),
            instrument_count=product.instrument_count,
            futures=None if product.futures is None else FuturesSpecResponse.of(product.futures),
            created_at=product.created_at,
        )


class LastReferenceResponse(BaseModel):
    """The instrument's latest preferred reference price, always shown with its own date, never
    as today's price (OQ-48, OQ-19 item 5)."""

    reference_date: date
    pu: str
    rate: str | None
    source: PriceSource

    @classmethod
    def of(cls, price: ReferencePriceRecord) -> Self:
        return cls(
            reference_date=price.reference_date,
            pu=to_plain(price.pu),
            rate=None if price.rate is None else to_plain(price.rate),
            source=price.source,
        )


class InstrumentResponse(BaseModel):
    id: UUID
    code: str
    product_id: UUID
    product_code: str
    maturity_date: date | None
    last_reference: LastReferenceResponse | None
    created_at: UtcDatetime

    @classmethod
    def of(cls, instrument: Instrument, last_reference: ReferencePriceRecord | None) -> Self:
        """``last_reference`` is ``None`` when the instrument has no price (OQ-48)."""
        return cls(
            id=instrument.id,
            code=instrument.code,
            product_id=instrument.product_id,
            product_code=instrument.product_code,
            maturity_date=instrument.maturity_date,
            last_reference=(
                None if last_reference is None else LastReferenceResponse.of(last_reference)
            ),
            created_at=instrument.created_at,
        )


class InstrumentTypeListResponse(BaseModel):
    items: list[InstrumentTypeResponse]


class ProductListResponse(BaseModel):
    items: list[ProductResponse]


class InstrumentListResponse(BaseModel):
    items: list[InstrumentResponse]


class CreateInstrumentRequest(RequestBody):
    """``POST /instruments``. ``maturity_date`` is always sent; ``null`` is accepted here because
    whether a maturity is required depends on the product's type, which the service checks."""

    product_id: UUID
    code: str
    maturity_date: date | None


class FuturesSpecRequest(RequestBody):
    face_value: DecimalString
    contract_multiplier: DecimalString = Decimal("1")
    settlement_method: str
    settlement_description: str | None = None

    def terms(self) -> FuturesTerms:
        return FuturesTerms(
            face_value=self.face_value,
            contract_multiplier=self.contract_multiplier,
            settlement_method=self.settlement_method,
            settlement_description=self.settlement_description,
        )


class CreateProductRequest(RequestBody):
    """``POST /products`` (interfaces.md "HTTP endpoints"). ``futures`` is required exactly for a
    product whose type is FUTURE, which the service checks."""

    asset_class_id: int
    code: str
    name: str
    futures: FuturesSpecRequest | None = None
