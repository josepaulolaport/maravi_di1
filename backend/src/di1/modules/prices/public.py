"""Prices' public contract: reference prices as other modules read them (interfaces.md "Prices").

Frozen in W0.3b. Lane D implements `PriceReader`; changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from di1.shared.input_kind import InputKind


class PriceSource(StrEnum):
    """Where an observation came from. When both exist for a date, MANUAL wins (spec §5)."""

    MANUAL = "MANUAL"
    B3 = "B3"


@dataclass(frozen=True, slots=True)
class ReferencePriceRecord:
    """One revision of a reference price (schema ``prices.reference_prices``).

    ``id`` identifies the exact revision used, for traceability (``position_metrics``
    ``reference_price_id``). ``superseded_at`` is ``None`` for the current revision.
    """

    id: UUID
    asset_id: UUID
    reference_date: date
    source: PriceSource
    input_kind: InputKind
    pu: Decimal
    rate: Decimal | None
    revision: int
    created_at: datetime
    superseded_at: datetime | None


class PriceReader(Protocol):
    """Exact-date reads: no carry-forward, weekends included (spec §5)."""

    async def get_preferred(
        self, asset_id: UUID, reference_date: date
    ) -> ReferencePriceRecord | None:
        """The current revision for exactly ``reference_date``, MANUAL before B3; else ``None``."""
        ...

    async def get_preferred_many(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        """`get_preferred` for every (asset, date) pair; pairs without a price are absent."""
        ...
