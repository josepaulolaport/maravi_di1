"""In-memory collaborators for `PriceService` unit tests.

The repository only records what the service passes on and returns canned rows: replacing a key,
the preferred source, exact dates and the latest date are SQL, tested against PostgreSQL in
``tests/integration/prices/test_reference_prices_persistence.py``. The unit tests price with
Pricing's real, pure service over `FakeAssets`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind
from tests.fakes.asset import CREATED_AT

SAVED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=SAO_PAULO)


def instrument(maturity_date: date | None = date(2028, 1, 3)) -> Instrument:
    product_id = uuid4()
    return Instrument(
        id=uuid4(),
        code="DI1F28",
        product_id=product_id,
        product_code="DI1",
        instrument_type="FUTURE",
        asset_class="INTEREST_RATE_FUTURE",
        maturity_date=maturity_date,
        face_value=Decimal("100000"),
        multiplier=Decimal("1"),
        settlement_method="CASH",
        created_at=CREATED_AT,
    )


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
class FakeAssets:
    instruments: dict[UUID, Instrument] = field(default_factory=dict)

    def add(self, descriptor: Instrument) -> Instrument:
        self.instruments[descriptor.id] = descriptor
        return descriptor

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self.instruments[i] for i in instrument_ids if i in self.instruments}


@dataclass
class PricingSpy:
    """The real `PricingService` over ``assets``, recording each call Prices makes to it."""

    assets: FakeAssets
    calls: list[tuple[UUID, date, Quote]] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append((instrument_id, reference_date, quote))
        return await build_pricing_service(self.assets).calculate(
            instrument_id, reference_date, quote
        )


@dataclass
class FakeUnitOfWork:
    commits: int = 0

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the unit tests never touch a session")

    async def commit(self) -> None:
        self.commits += 1


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
