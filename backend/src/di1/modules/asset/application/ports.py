"""What the Asset service needs from persistence. The repository maps rows to the domain read
models and holds no business rule; the service validates before it writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.asset.domain.model import (
    AssetClass,
    FuturesTerms,
    Instrument,
    InstrumentType,
    Product,
)


class AssetRepository(Protocol):
    async def list_instrument_types(self) -> Sequence[InstrumentType]:
        """Every type with its classes, ordered by code."""
        ...

    async def get_asset_class(
        self, asset_class_id: int
    ) -> tuple[AssetClass, InstrumentType] | None: ...

    async def product_code_exists(self, code: str) -> bool:
        """Case-insensitively, like ``instrument_code_exists``."""
        ...

    async def instrument_code_exists(self, code: str) -> bool: ...

    async def add_product(
        self, asset_class_id: int, code: str, name: str, futures: FuturesTerms | None
    ) -> UUID | None:
        """The product and, when given, its ``asset.futures`` row; ``None`` when the code was
        taken by a concurrent writer after the service's own check (the unique index)."""
        ...

    async def add_instrument(
        self, product_id: UUID, code: str, maturity_date: date | None
    ) -> UUID | None:
        """``None`` when the code is taken, as for ``add_product``."""
        ...

    async def list_products(self, instrument_type_code: str | None) -> Sequence[Product]:
        """Products of the type (case-insensitive code; every type when ``None``), by code."""
        ...

    async def get_product(self, product_id: UUID) -> Product | None: ...

    async def list_instruments(self, product_id: UUID | None) -> Sequence[Instrument]:
        """Instruments of the product (all when ``None``), by maturity, then code and id."""
        ...

    async def get_instrument(self, instrument_id: UUID) -> Instrument | None: ...
