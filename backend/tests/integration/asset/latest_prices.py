"""In-memory `prices.public.PriceReader` for Asset HTTP tests (OQ-48). Answers ``latest`` from a
mapping and records each call so a listing can be shown to read once."""

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
class FakePriceReader:
    """``latest`` only; exact-date ``get`` is unused by Asset HTTP."""

    by_asset: dict[UUID, ReferencePriceRecord] = field(default_factory=dict)
    calls: list[frozenset[UUID]] = field(default_factory=list)

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        raise AssertionError("Asset HTTP does not read a price for given dates")

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        asked = frozenset(asset_ids)
        self.calls.append(asked)
        return {asset_id: p for asset_id, p in self.by_asset.items() if asset_id in asked}
