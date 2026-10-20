"""Test doubles shared by every module's tests. Like production code, they reach other modules
only through their ``public.py``. A module's in-memory repositories stay with its unit tests.

The doubles store and answer; none re-implements a production rule (staff review §6, H2).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind


class FakeClock:
    """A `di1.shared.clock.Clock` the test controls (spec §15 D4: the challenge's 2027 examples
    run with a clock fixed at 01/01/2027). "Today" is ``today``; ``now`` starts at ``now`` (noon in
    São Paulo on ``today`` by default) and moves ``step`` forward before each read, so requests made
    one after the other keep their order (``created_at``, the queue's FIFO key). `advance` moves it
    by hand. Production reads real time through ``di1.platform.clock.SystemClock``."""

    def __init__(
        self, today: date, now: datetime | None = None, *, step: timedelta = timedelta(0)
    ) -> None:
        self._today = today
        self.current = now or datetime.combine(today, time(12, 0), tzinfo=SAO_PAULO)
        self._step = step

    def today(self) -> date:
        return self._today

    def now(self) -> datetime:
        self.current += self._step
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass
class FakeUnitOfWork:
    """The Unit of Work of in-memory repositories: counts commits and has no session."""

    commits: int = 0

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the in-memory repositories never use a session")

    async def commit(self) -> None:
        self.commits += 1


class FakeAssetReader:
    """`asset.public.AssetReader` over the instruments it is given; unknown ids are absent."""

    def __init__(self, *instruments: Instrument) -> None:
        self.instruments = {i.id: i for i in instruments}

    def add(self, instrument: Instrument) -> Instrument:
        self.instruments[instrument.id] = instrument
        return instrument

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self.instruments[i] for i in instrument_ids if i in self.instruments}


PRICED_AT = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
"""When a hand-built reference price was stored, unless the test says otherwise."""


def reference_price(
    asset_id: UUID,
    reference_date: date,
    pu: str,
    rate: str | None = None,
    source: PriceSource = PriceSource.MANUAL,
    *,
    created_at: datetime = PRICED_AT,
) -> ReferencePriceRecord:
    """A stored reference price as ``prices.public`` returns it: typed by rate when it has one."""
    return ReferencePriceRecord(
        id=uuid4(),
        asset_id=asset_id,
        reference_date=reference_date,
        source=source,
        input_kind=InputKind.RATE if rate is not None else InputKind.PU,
        pu=Decimal(pu),
        rate=None if rate is None else Decimal(rate),
        created_at=created_at,
        updated_at=created_at,
    )


@dataclass
class FakePriceReader:
    """`prices.public.PriceReader` over the records it is given, one per (asset, date): the
    preferred price, as the real reader returns it. Records each ``latest`` call; with
    ``dated_reads=False`` an exact-date ``get`` fails the test (a caller that must not make one)."""

    records: dict[tuple[UUID, date], ReferencePriceRecord] = field(default_factory=dict)
    dated_reads: bool = True
    latest_calls: list[frozenset[UUID]] = field(default_factory=list)

    def add(self, record: ReferencePriceRecord) -> ReferencePriceRecord:
        self.records[(record.asset_id, record.reference_date)] = record
        return record

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        if not self.dated_reads:
            raise AssertionError("this caller does not read a price for given dates")
        return {k: r for k, r in self.records.items() if k[0] in asset_ids and k[1] in dates}

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        asked = frozenset(asset_ids)
        self.latest_calls.append(asked)
        latest: dict[UUID, ReferencePriceRecord] = {}
        for (asset_id, _day), record in sorted(self.records.items()):
            if asset_id in asked:
                latest[asset_id] = record  # sorted by date: the last one wins
        return latest


CALCULATED_PU = Decimal("89006.4625467350")
CALCULATED_RATE = Decimal("0.100000000000")


@dataclass(frozen=True, slots=True)
class CalculationCall:
    instrument_id: UUID
    reference_date: date
    quote: Quote


@dataclass
class FakePricing:
    """A `pricing.public.PricingService` that keeps the typed value and returns a fixed one for
    the other side (`CALCULATED_PU`, `CALCULATED_RATE`), recording each call."""

    calls: list[CalculationCall] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append(CalculationCall(instrument_id, reference_date, quote))
        if quote.kind is InputKind.PU:
            return Price(pu=quote.value, rate=CALCULATED_RATE, input_kind=quote.kind)
        return Price(pu=CALCULATED_PU, rate=quote.value, input_kind=quote.kind)
