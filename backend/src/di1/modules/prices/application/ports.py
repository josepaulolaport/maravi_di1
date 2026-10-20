"""What `PriceService` and `DefaultPriceReader` need from persistence (interfaces.md "Prices").
The PU ↔ rate calculation is Pricing's public `PricingService`."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.modules.prices.domain.reference_price import PriceSource, ReferencePriceRecord
from di1.shared.input_kind import InputKind


class ReferencePriceRepository(Protocol):
    """``prices.reference_prices``: one row per (asset, date, source) (OQ-25). No rules here."""

    async def replace(
        self,
        *,
        asset_id: UUID,
        reference_date: date,
        source: PriceSource,
        input_kind: InputKind,
        pu: Decimal,
        rate: Decimal | None,
    ) -> ReferencePriceRecord:
        """Save this observation; an existing row of the same (asset, date, source) is replaced
        by it, with a new id and new timestamps (OQ-26 item 7)."""
        ...

    async def delete(self, price_id: UUID) -> ReferencePriceRecord | None:
        """Delete ``price_id``; the deleted row, or ``None`` when it did not exist."""
        ...

    async def find(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Sequence[ReferencePriceRecord]:
        """Every observation, of either source, of those assets on exactly those dates."""
        ...

    async def find_on_latest_date(
        self, asset_ids: Collection[UUID]
    ) -> Sequence[ReferencePriceRecord]:
        """For each of those assets, every observation, of either source, on the latest date that
        has one; assets without any observation contribute nothing."""
        ...

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        """Every observation of ``asset_id`` dated in [start_date, end_date]."""
        ...
