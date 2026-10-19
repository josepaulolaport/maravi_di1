"""An in-memory `prices.public.LatestPriceReader` for the Asset tests (OQ-48). It answers from a
fixed mapping and records each call, so a test can check that a listing reads once, in batch."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.shared.input_kind import InputKind


def price(
    asset_id: UUID,
    reference_date: date,
    pu: str,
    rate: str | None,
    source: PriceSource = PriceSource.MANUAL,
) -> ReferencePriceRecord:
    stamp = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
    return ReferencePriceRecord(
        id=uuid4(),
        asset_id=asset_id,
        reference_date=reference_date,
        source=source,
        input_kind=InputKind.RATE if rate is not None else InputKind.PU,
        pu=Decimal(pu),
        rate=None if rate is None else Decimal(rate),
        created_at=stamp,
        updated_at=stamp,
    )


@dataclass
class FakeLatestPrices:
    """Each asset's latest preferred price, as lane D's reader would choose it."""

    latest: dict[UUID, ReferencePriceRecord] = field(default_factory=dict)
    calls: list[frozenset[UUID]] = field(default_factory=list)

    async def get_latest_preferred_many(
        self, asset_ids: Collection[UUID]
    ) -> Mapping[UUID, ReferencePriceRecord]:
        asked = frozenset(asset_ids)
        self.calls.append(asked)
        return {asset_id: p for asset_id, p in self.latest.items() if asset_id in asked}
