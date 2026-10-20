"""Prices' public contract: reference prices as other modules read them (interfaces.md "Prices").

Frozen in W0.3b. Lane D implements `PriceReader`; changes go through the integrator. The record
and the source enum are Prices' domain types, re-exported here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.prices.domain.reference_price import PriceSource, ReferencePriceRecord

__all__ = ["PriceReader", "PriceSource", "ReferencePriceRecord"]


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
