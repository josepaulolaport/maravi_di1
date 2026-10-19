"""Prices' public contract: reference prices as other modules read them (interfaces.md "Prices").

Frozen in W0.3b. Lane D implements `PriceReader`; changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.shared.input_kind import InputKind
from di1.shared.quotes import PriceSource as PriceSource


@dataclass(frozen=True, slots=True)
class ReferencePriceRecord:
    """The reference price of one asset, date and source (schema ``prices.reference_prices``).

    There is one per (asset, date, source); a later set of the same key deletes the current row
    and inserts the new one, and a removal deletes it (OQ-25, OQ-26). Traceability is the current
    preferred price in this table (OQ-30), not ``id``.
    """

    id: UUID
    asset_id: UUID
    reference_date: date
    source: PriceSource
    input_kind: InputKind
    pu: Decimal
    rate: Decimal | None
    created_at: datetime
    updated_at: datetime


class PriceReader(Protocol):
    """Exact-date reads for other modules: MANUAL before B3, no carry-forward (spec §5). Missing
    keys mean no price. No source filter: the calendar that lists both sources lives in Prices.
    """

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        """One winning price per (asset, date); pairs without a price are absent."""
        ...

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        """Per asset, the winning price on the latest date that has one (OQ-48). Assets without
        a price are absent. Shown with that date, never as today's price (OQ-19)."""
        ...
