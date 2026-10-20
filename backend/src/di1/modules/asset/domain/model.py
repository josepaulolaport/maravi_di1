"""The Asset catalogue as the module reads it: type → class → product → instrument (spec §3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AssetClass:
    """An asset class (``INTEREST_RATE_FUTURE``); it belongs to one instrument type."""

    id: int
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class InstrumentType:
    """An instrument type with its asset classes, ordered by code."""

    id: int
    code: str
    name: str
    asset_classes: tuple[AssetClass, ...]


@dataclass(frozen=True, slots=True)
class FuturesTerms:
    """The shared specification of a futures product (``asset.futures``). The multiplier is stored
    but never applied (OQ-2)."""

    face_value: Decimal
    contract_multiplier: Decimal
    settlement_method: str
    settlement_description: str | None


@dataclass(frozen=True, slots=True)
class Product:
    """A product (``DI1``) with its classification, its futures specification (``None`` unless
    the type is FUTURE) and how many instruments it has."""

    id: UUID
    code: str
    name: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    instrument_count: int
    futures: FuturesTerms | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Instrument:
    """A contract (``DI1F27``) with the product's specification other modules price from.

    ``instrument_type`` and ``asset_class`` are catalogue codes. Futures fields are ``None`` when
    the product is not a future.
    """

    id: UUID
    code: str
    product_id: UUID
    product_code: str
    instrument_type: str
    asset_class: str
    maturity_date: date | None
    face_value: Decimal | None
    multiplier: Decimal | None
    settlement_method: str | None
    created_at: datetime
