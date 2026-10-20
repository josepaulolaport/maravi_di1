"""In-memory collaborators for `PriceService` unit tests."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind


@dataclass
class InMemoryRepository:
    rows: dict[UUID, ReferencePriceRecord] = field(default_factory=dict)
    ticks: int = 0

    def _now(self) -> datetime:
        self.ticks += 1
        return datetime(2026, 10, 19, 10, 0, tzinfo=SAO_PAULO) + timedelta(minutes=self.ticks)

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
        for key, row in list(self.rows.items()):
            if (row.asset_id, row.reference_date, row.source) == (
                asset_id,
                reference_date,
                source,
            ):
                del self.rows[key]
        now = self._now()
        record = ReferencePriceRecord(
            id=uuid4(),
            asset_id=asset_id,
            reference_date=reference_date,
            source=source,
            input_kind=input_kind,
            pu=pu,
            rate=rate,
            created_at=now,
            updated_at=now,
        )
        self.rows[record.id] = record
        return record

    async def delete(self, price_id: UUID) -> ReferencePriceRecord | None:
        return self.rows.pop(price_id, None)

    async def find(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Sequence[ReferencePriceRecord]:
        return [
            r for r in self.rows.values() if r.asset_id in asset_ids and r.reference_date in dates
        ]

    async def find_on_latest_date(
        self, asset_ids: Collection[UUID]
    ) -> Sequence[ReferencePriceRecord]:
        latest: dict[UUID, date] = {}
        for r in self.rows.values():
            if r.asset_id in asset_ids:
                latest[r.asset_id] = max(latest.get(r.asset_id, r.reference_date), r.reference_date)
        return [r for r in self.rows.values() if latest.get(r.asset_id) == r.reference_date]

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        return [
            r
            for r in self.rows.values()
            if r.asset_id == asset_id and start_date <= r.reference_date <= end_date
        ]
