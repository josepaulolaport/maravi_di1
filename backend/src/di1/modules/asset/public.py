"""Asset's public contract: what other modules may know about an instrument (interfaces.md "Asset").

Frozen in W0.3b. Lane A implements `AssetReader`; changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InstrumentDescriptor:
    """One tradable instrument with its product's specification (schema ``asset.*``).

    ``instrument_type`` and ``asset_class`` are the catalogue codes (``FUTURE``,
    ``INTEREST_RATE_FUTURE``). The futures fields come from the product's ``asset.futures`` row
    and are ``None`` for a product that is not a future; ``maturity_date`` is required for a
    future. ``multiplier`` is stored but never applied (OQ-2).
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


class AssetReader(Protocol):
    """Read access for Pricing, Ledger, Prices, Portfolio and Processing."""

    async def get_instrument(self, instrument_id: UUID) -> InstrumentDescriptor:
        """The instrument; raises ``DomainError(NOT_FOUND)`` when it does not exist."""
        ...

    async def get_instruments(
        self, instrument_ids: Collection[UUID]
    ) -> Mapping[UUID, InstrumentDescriptor]:
        """The instruments that exist among ``instrument_ids``; unknown ids are absent."""
        ...
