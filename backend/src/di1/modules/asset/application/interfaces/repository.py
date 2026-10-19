"""What the Asset services need from persistence. The repository maps rows to these read models
and holds no business rule; the services validate before they write."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.asset.domain.model import (
    AssetClass,
    ClassifiedAssetClass,
    Instrument,
    InstrumentType,
    InstrumentTypeRef,
    Product,
)
from di1.modules.asset.domain.rules import FuturesTerms
from di1.modules.asset.public import InstrumentDescriptor


class DuplicateCodeError(Exception):
    """A code is already taken, case-insensitively; raised when a concurrent insert won the race
    after the service's own check."""


class AssetRepository(Protocol):
    async def list_instrument_types(self) -> Sequence[InstrumentType]:
        """Every type with its classes, ordered by code."""
        ...

    async def get_instrument_type(self, instrument_type_id: int) -> InstrumentTypeRef | None: ...

    async def get_asset_class(self, asset_class_id: int) -> ClassifiedAssetClass | None: ...

    async def instrument_type_code_exists(self, code: str) -> bool:
        """Case-insensitively, like every code check below."""
        ...

    async def asset_class_code_exists(self, code: str) -> bool: ...

    async def product_code_exists(self, code: str) -> bool: ...

    async def instrument_code_exists(self, code: str) -> bool: ...

    async def add_instrument_type(self, code: str, name: str) -> InstrumentTypeRef:
        """Raises `DuplicateCodeError` when the code is taken."""
        ...

    async def add_asset_class(self, instrument_type_id: int, code: str, name: str) -> AssetClass:
        """Raises `DuplicateCodeError` when the code is taken."""
        ...

    async def add_product(
        self, asset_class_id: int, code: str, name: str, futures: FuturesTerms | None
    ) -> UUID:
        """The product and, when given, its ``asset.futures`` row. Raises `DuplicateCodeError`."""
        ...

    async def add_instrument(self, product_id: UUID, code: str, maturity_date: date | None) -> UUID:
        """Raises `DuplicateCodeError` when the code is taken."""
        ...

    async def list_products(self, instrument_type_code: str | None) -> Sequence[Product]:
        """Products of the type (case-insensitive code; every type when ``None``), by code."""
        ...

    async def get_product(self, product_id: UUID) -> Product | None: ...

    async def list_instruments(self, product_id: UUID | None) -> Sequence[Instrument]:
        """Instruments of the product (all when ``None``), by maturity, then code and id."""
        ...

    async def get_instrument(self, instrument_id: UUID) -> Instrument | None: ...

    async def get_descriptors(
        self, instrument_ids: Collection[UUID]
    ) -> Mapping[UUID, InstrumentDescriptor]:
        """The descriptors of the instruments that exist among ``instrument_ids``."""
        ...
