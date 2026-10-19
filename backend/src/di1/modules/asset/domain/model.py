"""The Asset catalogue as the module reads it: type → class → product → instrument (spec §3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from di1.modules.asset.domain.rules import FuturesTerms


@dataclass(frozen=True, slots=True)
class InstrumentTypeRef:
    """An instrument type without its classes (``FUTURE``)."""

    id: int
    code: str
    name: str


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
class ClassifiedAssetClass:
    """An asset class and the instrument type it belongs to."""

    asset_class: AssetClass
    instrument_type: InstrumentTypeRef


@dataclass(frozen=True, slots=True)
class Product:
    """A product (``DI1``) with its classification, its futures specification (``None`` unless
    the type is FUTURE) and how many instruments it has."""

    id: UUID
    code: str
    name: str
    asset_class: AssetClass
    instrument_type: InstrumentTypeRef
    instrument_count: int
    futures: FuturesTerms | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Instrument:
    """A contract (``DI1F27``) of a product, with its own maturity."""

    id: UUID
    code: str
    product_id: UUID
    product_code: str
    maturity_date: date | None
    created_at: datetime
