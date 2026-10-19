"""In-memory collaborators for `PriceService` unit tests."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import InstrumentDescriptor
from di1.modules.prices.application.interfaces.ports import NewReferencePrice
from di1.modules.prices.public import ReferencePriceRecord
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import SAO_PAULO
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

CALCULATED_PU = Decimal("89006.4625467350")
CALCULATED_RATE = Decimal("0.100000000000")


def instrument(maturity_date: date | None = date(2028, 1, 3)) -> InstrumentDescriptor:
    product_id = uuid4()
    return InstrumentDescriptor(
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
    )


@dataclass
class FakeAssets:
    instruments: dict[UUID, InstrumentDescriptor] = field(default_factory=dict)

    def add(self, descriptor: InstrumentDescriptor) -> InstrumentDescriptor:
        self.instruments[descriptor.id] = descriptor
        return descriptor

    async def get_instrument(self, instrument_id: UUID) -> InstrumentDescriptor:
        if instrument_id not in self.instruments:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        return self.instruments[instrument_id]

    async def get_instruments(
        self, instrument_ids: Collection[UUID]
    ) -> Mapping[UUID, InstrumentDescriptor]:
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

    async def replace(self, price: NewReferencePrice) -> ReferencePriceRecord:
        for key, row in list(self.rows.items()):
            if (row.asset_id, row.reference_date, row.source) == (
                price.asset_id,
                price.reference_date,
                price.source,
            ):
                del self.rows[key]
        now = self._now()
        record = ReferencePriceRecord(
            id=uuid4(),
            asset_id=price.asset_id,
            reference_date=price.reference_date,
            source=price.source,
            input_kind=price.input_kind,
            pu=price.pu,
            rate=price.rate,
            created_at=now,
            updated_at=now,
        )
        self.rows[record.id] = record
        return record

    async def update(
        self, price_id: UUID, input_kind: InputKind, pu: Decimal, rate: Decimal | None
    ) -> ReferencePriceRecord | None:
        if price_id not in self.rows:
            return None
        record = replace(
            self.rows[price_id], input_kind=input_kind, pu=pu, rate=rate, updated_at=self._now()
        )
        self.rows[price_id] = record
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

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        return [
            r
            for r in self.rows.values()
            if r.asset_id == asset_id and start_date <= r.reference_date <= end_date
        ]
