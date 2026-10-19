"""HTTP shapes of the Asset routes: the frontend contract ``frontend/src/api/contract/asset.ts``
(OQ-26 item 8). Decimals cross as strings in plain notation; absent values are ``null``.
Schemas check syntax only; business rules are the service's."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from di1.modules.asset.domain.model import (
    AssetClass,
    Instrument,
    InstrumentType,
    InstrumentTypeRef,
    Product,
)
from di1.modules.asset.domain.rules import FuturesTerms
from di1.modules.prices.public import PriceSource
from di1.shared.decimals import to_plain


class AssetClassOut(BaseModel):
    id: int
    code: str
    name: str

    @classmethod
    def of(cls, asset_class: AssetClass) -> AssetClassOut:
        return cls(id=asset_class.id, code=asset_class.code, name=asset_class.name)


class InstrumentTypeRefOut(BaseModel):
    id: int
    code: str
    name: str

    @classmethod
    def of(cls, instrument_type: InstrumentTypeRef) -> InstrumentTypeRefOut:
        return cls(id=instrument_type.id, code=instrument_type.code, name=instrument_type.name)


class InstrumentTypeOut(BaseModel):
    id: int
    code: str
    name: str
    asset_classes: list[AssetClassOut]

    @classmethod
    def of(cls, instrument_type: InstrumentType) -> InstrumentTypeOut:
        return cls(
            id=instrument_type.id,
            code=instrument_type.code,
            name=instrument_type.name,
            asset_classes=[AssetClassOut.of(c) for c in instrument_type.asset_classes],
        )


class FuturesSpecOut(BaseModel):
    face_value: str
    contract_multiplier: str
    settlement_method: str
    settlement_description: str | None

    @classmethod
    def of(cls, futures: FuturesTerms) -> FuturesSpecOut:
        return cls(
            face_value=to_plain(futures.face_value),
            contract_multiplier=to_plain(futures.contract_multiplier),
            settlement_method=futures.settlement_method,
            settlement_description=futures.settlement_description,
        )


class ProductOut(BaseModel):
    id: UUID
    code: str
    name: str
    asset_class: AssetClassOut
    instrument_type: InstrumentTypeRefOut
    instrument_count: int
    futures: FuturesSpecOut | None
    created_at: datetime

    @classmethod
    def of(cls, product: Product) -> ProductOut:
        return cls(
            id=product.id,
            code=product.code,
            name=product.name,
            asset_class=AssetClassOut.of(product.asset_class),
            instrument_type=InstrumentTypeRefOut.of(product.instrument_type),
            instrument_count=product.instrument_count,
            futures=None if product.futures is None else FuturesSpecOut.of(product.futures),
            created_at=product.created_at,
        )


class LastReferenceOut(BaseModel):
    """The instrument's latest reference observation, always shown with its own date (OQ-19
    item 5). Declared for the contract; not yet filled (see `InstrumentOut`)."""

    reference_date: date
    pu: str
    rate: str | None
    source: PriceSource


class InstrumentOut(BaseModel):
    id: UUID
    code: str
    product_id: UUID
    product_code: str
    maturity_date: date | None
    # The latest reference observation needs a Prices read that does not exist yet; until it
    # does, the contract's field is always null (user, 2026-10-19).
    last_reference: LastReferenceOut | None = None
    created_at: datetime

    @classmethod
    def of(cls, instrument: Instrument) -> InstrumentOut:
        return cls(
            id=instrument.id,
            code=instrument.code,
            product_id=instrument.product_id,
            product_code=instrument.product_code,
            maturity_date=instrument.maturity_date,
            created_at=instrument.created_at,
        )


class InstrumentTypeList(BaseModel):
    items: list[InstrumentTypeOut]


class ProductList(BaseModel):
    items: list[ProductOut]


class InstrumentList(BaseModel):
    items: list[InstrumentOut]


class CreateInstrumentIn(BaseModel):
    """``POST /instruments``. ``maturity_date`` is always sent; ``null`` is accepted here because
    whether a maturity is required depends on the product's type, which the service checks."""

    product_id: UUID
    code: str
    maturity_date: date | None


PlainDecimal = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+(\.[0-9]+)?$")]
"""A decimal as a JSON string in plain notation ("100000", "0.5"): never a JSON number, an
exponent or a non-finite value (CLAUDE.md §2)."""


class FuturesSpecIn(BaseModel):
    face_value: PlainDecimal
    contract_multiplier: PlainDecimal = "1"
    settlement_method: str
    settlement_description: str | None = None

    def terms(self) -> FuturesTerms:
        return FuturesTerms(
            face_value=Decimal(self.face_value),
            contract_multiplier=Decimal(self.contract_multiplier),
            settlement_method=self.settlement_method,
            settlement_description=self.settlement_description,
        )


class CreateProductIn(BaseModel):
    """``POST /products`` (interfaces.md "HTTP endpoints"). ``futures`` is required exactly for a
    product whose type is FUTURE, which the service checks."""

    asset_class_id: int
    code: str
    name: str
    futures: FuturesSpecIn | None = None
