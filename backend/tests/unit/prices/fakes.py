"""In-memory collaborators for `PriceService` unit tests."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind
from tests.fakes.asset import CREATED_AT

CALCULATED_PU = Decimal("89006.4625467350")
CALCULATED_RATE = Decimal("0.100000000000")


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


@dataclass
class FakeAssets:
    instruments: dict[UUID, Instrument] = field(default_factory=dict)

    def add(self, descriptor: Instrument) -> Instrument:
        self.instruments[descriptor.id] = descriptor
        return descriptor

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self.instruments[i] for i in instrument_ids if i in self.instruments}


@dataclass(frozen=True, slots=True)
class CalculationCall:
    instrument_id: UUID
    reference_date: date
    quote: Quote


@dataclass
class FakePricing:
    """A `pricing.public.PricingService` that keeps the typed value and returns a fixed one for
    the other side."""

    calls: list[CalculationCall] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append(CalculationCall(instrument_id, reference_date, quote))
        if quote.kind is InputKind.PU:
            return Price(pu=quote.value, rate=CALCULATED_RATE, input_kind=quote.kind)
        return Price(pu=CALCULATED_PU, rate=quote.value, input_kind=quote.kind)


@dataclass
class FakeUnitOfWork:
    commits: int = 0

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the unit tests never touch a session")

    async def commit(self) -> None:
        self.commits += 1


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

    async def get(self, price_id: UUID) -> ReferencePriceRecord | None:
        return self.rows.get(price_id)

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
