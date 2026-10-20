"""Test doubles shared by every module's tests. They reach other modules through their
``public.py``, except Processing's `ChainPorts` (the chain steps' port bundle, which `World`
builds). A module's in-memory repositories stay with its unit tests.

The doubles store and answer; none re-implements a production rule (staff review §6, H2).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.ledger.public import EntryType, LedgerEntry
from di1.modules.pnl.public import AssetPnLResult, PortfolioPnLResult
from di1.modules.portfolio.public import (
    CashBalance,
    CashDay,
    PortfolioResultsWriter,
    PortfolioValuation,
    PositionsDay,
    PreviousPositionsDay,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import Price, Quote
from di1.modules.processing.application.ports import ChainPorts
from di1.modules.processing.public import Chain, DateStatus
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind
from tests.support.builders import T0


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


def stepping_clock(start: datetime = T0) -> FakeClock:
    """A clock whose every ``now`` is one second after the previous one, from ``start``: FIFO
    order by ``created_at`` is then observable."""
    return FakeClock(start.date(), start, step=timedelta(seconds=1))


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

    def set(
        self,
        asset_id: UUID,
        reference_date: date,
        pu: str,
        source: PriceSource = PriceSource.MANUAL,
        rate: str | None = None,
        *,
        created_at: datetime = PRICED_AT,
    ) -> ReferencePriceRecord:
        """The preferred price of ``(asset_id, reference_date)`` is now this one."""
        return self.add(
            reference_price(asset_id, reference_date, pu, rate, source, created_at=created_at)
        )

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


@dataclass
class PricingSpy:
    """The real, pure `pricing.public.PricingService` over ``assets``, recording each call: a test
    sees what its caller passed to Pricing without a copy of the DC/365 formula."""

    assets: FakeAssetReader
    calls: list[tuple[UUID, date, Quote]] = field(default_factory=list)

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        self.calls.append((instrument_id, reference_date, quote))
        return await build_pricing_service(self.assets).calculate(
            instrument_id, reference_date, quote
        )


class FakeDateStatusReader:
    """`processing.public.DateStatusReader` over the rows it is given; counts its reads."""

    def __init__(self, statuses: Mapping[date, DateStatus] | None = None) -> None:
        self.statuses = dict(statuses or {})
        self.reads = 0

    async def get_date_statuses(
        self, start_date: date, end_date: date
    ) -> Mapping[date, DateStatus]:
        self.reads += 1
        return {d: s for d, s in self.statuses.items() if start_date <= d <= end_date}


@dataclass
class FakeLedger:
    """`ledger.public.LedgerReader` over the entries it is given; records each existence check."""

    trades: list[LedgerEntry] = field(default_factory=list)
    movements: list[LedgerEntry] = field(default_factory=list)
    asked: list[tuple[date, EntryType | None]] = field(default_factory=list)

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        found = [t for t in self.trades if start_date <= t.entry_date <= end_date]
        return sorted(found, key=lambda t: t.order_key)

    async def get_cash_movements(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        found = [m for m in self.movements if start_date <= m.entry_date <= end_date]
        return sorted(found, key=lambda m: m.order_key)

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        self.asked.append((day, entry_type))
        trades = any(t.entry_date <= day for t in self.trades)
        if entry_type is EntryType.TRADE:
            return trades
        return trades or any(m.entry_date <= day for m in self.movements)


@dataclass
class FakePortfolio:
    """`portfolio.public.PortfolioReader`: the published D−1 of each chain, keyed by D−1."""

    positions: dict[date, PreviousPositionsDay] = field(default_factory=dict)
    cash: dict[date, CashBalance] = field(default_factory=dict)

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        return self.positions.get(before_date - timedelta(days=1))

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        return self.cash.get(before_date - timedelta(days=1))


# Processing's ports: what its chain steps read and write, and the zero-state question.


@dataclass
class FakeChainHistory:
    """Processing's `ChainHistory`: the first dated entry of each chain, or none; records each
    question."""

    first_trade: date | None = None
    first_cash_movement: date | None = None
    asked: list[tuple[Chain, date]] = field(default_factory=list)

    async def has_entries_on_or_before(self, chain: Chain, day: date) -> bool:
        self.asked.append((chain, day))
        firsts = [self.first_trade]
        if chain is Chain.CASH:
            firsts.append(self.first_cash_movement)
        return any(first is not None and first <= day for first in firsts)


@dataclass(frozen=True)
class PositionsWrite:
    day: PositionsDay
    valuation: PortfolioValuation
    asset_pnl: Mapping[UUID, AssetPnLResult]
    pnl: PortfolioPnLResult


@dataclass(frozen=True)
class CashWrite:
    day: CashDay


@dataclass
class RecordingWriter:
    """`portfolio.public.PortfolioResultsWriter` that records what it was given."""

    positions: list[PositionsWrite] = field(default_factory=list)
    cash: list[CashWrite] = field(default_factory=list)

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        self.positions.append(PositionsWrite(day, valuation, asset_pnl, pnl))

    async def write_cash_day(self, day: CashDay) -> None:
        self.cash.append(CashWrite(day))


@dataclass
class World:
    """Everything Processing's chain steps read: Ledger, Prices, Asset and Portfolio."""

    ledger: FakeLedger = field(default_factory=FakeLedger)
    prices: FakePriceReader = field(default_factory=FakePriceReader)
    instruments: FakeAssetReader = field(default_factory=FakeAssetReader)
    portfolio: FakePortfolio = field(default_factory=FakePortfolio)

    def ports(self, writer: PortfolioResultsWriter) -> ChainPorts:
        return ChainPorts(
            ledger=self.ledger,
            prices=self.prices,
            assets=self.instruments,
            portfolio=self.portfolio,
            writer=writer,
        )
