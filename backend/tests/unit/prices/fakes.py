"""In-memory collaborators for `PriceService` unit tests.

The repository only records what the service passes on and returns canned rows: replacing a key,
the preferred source, exact dates and the latest date are SQL, tested against PostgreSQL in
``tests/integration/prices/test_reference_prices_persistence.py``. The unit tests price with
Pricing's real, pure service over ``tests.support.fakes.FakeAssetReader``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind

SAVED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=SAO_PAULO)


def record(
    asset_id: UUID,
    reference_date: date,
    source: PriceSource,
    pu: str = "89250.3147019396",
) -> ReferencePriceRecord:
    """A stored row, as the repository would return it."""
    return ReferencePriceRecord(
        id=uuid4(),
        asset_id=asset_id,
        reference_date=reference_date,
        source=source,
        input_kind=InputKind.PU,
        pu=Decimal(pu),
        rate=None,
        created_at=SAVED_AT,
        updated_at=SAVED_AT,
    )


@dataclass
class RecordingRepository:
    """A `ReferencePriceRepository` that records every call and answers with ``rows`` (filtered by
    nothing) or, for ``delete``, the row of that id in ``rows``."""

    rows: list[ReferencePriceRecord] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

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
        saved = ReferencePriceRecord(
            id=uuid4(),
            asset_id=asset_id,
            reference_date=reference_date,
            source=source,
            input_kind=input_kind,
            pu=pu,
            rate=rate,
            created_at=SAVED_AT,
            updated_at=SAVED_AT,
        )
        self.calls.append(
            (
                "replace",
                {
                    "asset_id": asset_id,
                    "reference_date": reference_date,
                    "source": source,
                    "input_kind": input_kind,
                    "pu": pu,
                    "rate": rate,
                },
            )
        )
        return saved

    async def delete(self, price_id: UUID) -> ReferencePriceRecord | None:
        self.calls.append(("delete", {"price_id": price_id}))
        return next((r for r in self.rows if r.id == price_id), None)

    async def find(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Sequence[ReferencePriceRecord]:
        self.calls.append(("find", {"asset_ids": asset_ids, "dates": dates}))
        return self.rows

    async def find_on_latest_date(
        self, asset_ids: Collection[UUID]
    ) -> Sequence[ReferencePriceRecord]:
        self.calls.append(("find_on_latest_date", {"asset_ids": asset_ids}))
        return self.rows

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        self.calls.append(
            (
                "find_in_range",
                {"asset_id": asset_id, "start_date": start_date, "end_date": end_date},
            )
        )
        return self.rows
